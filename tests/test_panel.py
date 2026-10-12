import asyncio
import copy
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
from contextlib import asynccontextmanager
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import panel
import panel_bridge as bridge
from sqlalchemy import JSON,Integer,String,select,update
from sqlalchemy.orm import DeclarativeBase,Mapped,mapped_column
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker

OLD='https://old.example.test'
NEW='https://new.example.test'
OTHER={'announce':'Preserve this announcement','profile_title':'Plan','response_headers':{'profile-update-interval':'12'},'support_url':'https://support.example.test'}
class Base(DeclarativeBase):pass
class Settings(Base):
    __tablename__='settings'
    id:Mapped[int]=mapped_column(Integer,primary_key=True)
    subscription:Mapped[dict]=mapped_column(JSON)
    general:Mapped[dict]=mapped_column(JSON)
class Customer(Base):
    __tablename__='customers'
    id:Mapped[int]=mapped_column(Integer,primary_key=True)
    credential:Mapped[str]=mapped_column(String)
    quota:Mapped[int]=mapped_column(Integer)

class AtomicUpdateTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine=create_async_engine('sqlite+aiosqlite:///:memory:')
        async with self.engine.begin() as conn:await conn.run_sync(Base.metadata.create_all)
        self.sessions=async_sessionmaker(self.engine,expire_on_commit=False)
        async with self.sessions() as db:
            db.add(Settings(id=1,subscription=dict(OTHER,url_prefix=OLD),general={'preserve':'general'}))
            db.add(Customer(id=7,credential='SYNTHETIC-ONLY',quota=53687091200));await db.commit()
        @asynccontextmanager
        async def database():
            async with self.sessions() as db:yield db
        self.context=patch.object(bridge,'Database',database);self.context.start()
        native=types.ModuleType('app.db');native.models=types.SimpleNamespace(Settings=Settings)
        self.modules=patch.dict(sys.modules,{'app.db':native});self.modules.start()
    async def asyncTearDown(self):
        self.context.stop();self.modules.stop();await self.engine.dispose()
    async def read(self):
        async with self.sessions() as db:return copy.deepcopy((await db.get(Settings,1)).subscription)
    async def assert_preserved(self):
        async with self.sessions() as db:
            row=await db.get(Settings,1);customer=await db.get(Customer,7)
            self.assertEqual(row.general,{'preserve':'general'})
            self.assertEqual(customer.credential,'SYNTHETIC-ONLY');self.assertEqual(customer.quota,53687091200)
            data=copy.deepcopy(row.subscription);data.pop('url_prefix',None);self.assertEqual(data,OTHER)
    async def test_only_prefix_changes(self):
        await bridge.atomic_prefix(1,OLD,NEW)
        self.assertEqual((await self.read())['url_prefix'],NEW);await self.assert_preserved()
    async def test_concurrent_prefix_edit_is_not_overwritten(self):
        with self.assertRaises(ValueError):await bridge.atomic_prefix(1,'https://stale.example.test',NEW)
        self.assertEqual((await self.read())['url_prefix'],OLD);await self.assert_preserved()
    async def test_unrelated_subscription_edit_is_preserved(self):
        async with self.sessions() as db:
            row=await db.get(Settings,1);row.subscription=dict(row.subscription,announce='Concurrent announcement');await db.commit()
        await bridge.atomic_prefix(1,OLD,NEW)
        self.assertEqual((await self.read())['announce'],'Concurrent announcement')
    async def test_rollback_restores_empty_prefix(self):
        await bridge.atomic_prefix(1,OLD,NEW);await bridge.atomic_prefix(1,NEW,'')
        self.assertEqual((await self.read())['url_prefix'],'');await self.assert_preserved()
    async def test_rollback_removes_previously_absent_key(self):
        await bridge.atomic_prefix(1,OLD,NEW);await bridge.atomic_prefix(1,NEW,'',remove=True)
        self.assertNotIn('url_prefix',await self.read());await self.assert_preserved()
    async def test_atomic_update_rejects_wrong_settings_row(self):
        with self.assertRaises(ValueError):await bridge.atomic_prefix(77,OLD,NEW)
        self.assertEqual((await self.read())['url_prefix'],OLD)
    async def test_identity_mismatch_withholds_update(self):
        state={'fingerprint':'synthetic','token':'SYNTHETIC-ONLY','row_id':1,'subscription':await self.read()}
        async def identity():return state
        with patch.object(bridge,'endpoint',return_value={}),patch.object(bridge,'identity',identity):
            with self.assertRaises(ValueError):await bridge.execute({'command':'update','fingerprint':'other','expected_url':OLD,'url':NEW})
        self.assertEqual((await self.read())['url_prefix'],OLD)
    async def test_api_cache_refresh_failure_compensates_prefix(self):
        state={'fingerprint':'synthetic','token':'SYNTHETIC-ONLY','row_id':1,'subscription':await self.read()}
        async def identity():return state
        def api(details,token,method='GET',body=None):
            if method=='PUT':raise ValueError('Synthetic cache refresh failure')
            return {'subscription':copy.deepcopy(state['subscription'])}
        with patch.object(bridge,'endpoint',return_value={}),patch.object(bridge,'identity',identity),patch.object(bridge,'api',api):
            with self.assertRaises(ValueError):await bridge.execute({'command':'update','expected_url':OLD,'url':NEW})
        self.assertEqual((await self.read())['url_prefix'],OLD);await self.assert_preserved()
    async def test_api_cache_refresh_uses_empty_patch(self):
        state={'fingerprint':'synthetic','token':'SYNTHETIC-ONLY','row_id':1,'subscription':await self.read()};calls=[]
        async def identity():return state
        def api(details,token,method='GET',body=None):
            calls.append((method,body))
            return {'subscription':dict(state['subscription'],url_prefix=NEW if method=='PUT' else OLD)}
        with patch.object(bridge,'endpoint',return_value={}),patch.object(bridge,'identity',identity),patch.object(bridge,'api',api):
            response=await bridge.execute({'command':'update','expected_url':OLD,'url':NEW})
        self.assertTrue(response['updated']);self.assertEqual(calls,[('GET',None),('PUT',{})]);await self.assert_preserved()

class DiscoveryTest(unittest.TestCase):
    def candidate(self,name='panel',cid='a'*64):return {'locator':{'kind':'docker','name':name,'id':cid},'details':{},'origins':[]}
    def test_one_panel_is_selected_automatically(self):
        value=self.candidate();self.assertEqual(panel.choose([value]),value)
    def test_multiple_panels_are_not_guessed(self):
        with self.assertRaises(ValueError):panel.choose([self.candidate(),self.candidate('second','b'*64)])
    def test_explicit_panel_selection(self):
        second=self.candidate('second','b'*64);self.assertEqual(panel.choose([self.candidate(),second],'second'),second)
    def test_missing_panel_gives_clear_failure(self):
        with self.assertRaisesRegex(ValueError,'No supported local'):panel.choose([])
    def test_rollback_keeps_independent_url_change(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            (path/'panel-locator.json').write_text(json.dumps({'locator':{'kind':'docker','id':'a'*64},'fingerprint':'synthetic'}))
            (path/'panel-update.json').write_text(json.dumps({'old_url':OLD,'new_url':NEW,'old_key_present':True}))
            with patch.object(panel,'run_bridge',return_value={'old_url':'https://independent.example.test'}) as call:
                with self.assertRaisesRegex(ValueError,'independently'):panel.restore(directory)
            self.assertEqual(call.call_count,1)
    def test_root_bridge_token_not_in_command_arguments(self):
        response=MagicMock(returncode=0,stdout=b'VTWSUB_RESULT={"updated":true}\n',stderr=b'')
        with patch.object(panel.subprocess,'run',return_value=response) as execute:
            panel.run_bridge({'kind':'docker','id':'a'*64},'update',{'url':NEW,'expected_url':OLD})
        args=execute.call_args.args[0]
        self.assertEqual(args,['docker','exec','-i','a'*64,'python','-'])
        self.assertNotIn(NEW,' '.join(args))

if __name__=='__main__':unittest.main(verbosity=2)
