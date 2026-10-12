// Browser checks use synthetic subscription credentials and never contact customers.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const frontend = path.join(root, 'web');
const privateKey = Buffer.alloc(32, 1).toString('base64'), publicKey = Buffer.alloc(32, 2).toString('base64'), psk = Buffer.alloc(32, 3).toString('base64');
const wg = name => 'wireguard://' + encodeURIComponent(privateKey) + '@' + (name.startsWith('Turkey') ? 'turkey' : 'finland') + '.example.test:443?publickey=' + encodeURIComponent(publicKey) + '&address=10.77.0.2%2F32&mtu=1280#' + encodeURIComponent(name);
const finland = wg('Finland WireGuard Direct'), turkey = wg('Turkey WireGuard Tunnel');
const dualStack = 'wireguard://' + encodeURIComponent(privateKey) + '@[2001:db8::1]:51820?' + new URLSearchParams({publicKey, ip:'10.88.0.2/32,fd01::2/128', dns:'1.1.1.1,2606:4700:4700::1111', mtu:'1280', allowedIPs:'0.0.0.0/0,::/0', presharedkey:psk, keepalive:'25'}) + '#' + encodeURIComponent('🇹🇷 سرور وایرگارد');
const invalidProfile = finland.replace('10.77.0.2%2F32', '10.77.0.2%2F32%0APostUp%20%3D%20bad');
const expectedWG = host => `[Interface]\nPrivateKey = ${privateKey}\nAddress = 10.77.0.2/32\nMTU = 1280\n\n[Peer]\nPublicKey = ${publicKey}\nEndpoint = ${host}.example.test:443\nAllowedIPs = 0.0.0.0/0, ::/0\n`;
const expectedDualStack = `[Interface]\nPrivateKey = ${privateKey}\nAddress = 10.88.0.2/32, fd01::2/128\nDNS = 1.1.1.1, 2606:4700:4700::1111\nMTU = 1280\n\n[Peer]\nPublicKey = ${publicKey}\nEndpoint = [2001:db8::1]:51820\nAllowedIPs = 0.0.0.0/0, ::/0\nPresharedKey = ${psk}\nPersistentKeepalive = 25\n`;
const vless = 'vless://11111111-1111-4111-8111-111111111111@example.test:443#Germany%20VLESS';
const hy2 = 'hy2://synthetic@example.test:443#Finland%20Hysteria';
const cases = [
  {name: 'wg-plain', lines: [finland, turkey], base64: false},
  {name: 'wg-base64', lines: [finland, turkey], base64: true},
  {name: 'mixed-plain', lines: [vless, finland, turkey, hy2], base64: false},
  {name: 'mixed-base64', lines: [vless, finland, turkey, hy2], base64: true},
  {name: 'wg-unlimited', lines: [finland, turkey], base64: true, unlimited: true},
  {name: 'wg-expired', lines: [finland, turkey], base64: true, expired: true},
  {name: 'empty', lines: [], base64: false},
  {name: 'upstream-error', lines: [], error: true},
  {name: 'signed-wg-plain', lines: [finland, turkey], signed: true},
  {name: 'signed-mixed-base64', lines: [vless, finland, turkey, hy2], base64: true, signed: true},
  {name: 'wg-dual-stack', lines: [dualStack], base64: true, signed: true, width: 320},
  {name: 'wg-invalid', lines: [invalidProfile]},
  {name: 'non-wg', lines: [vless, hy2]},
];
async function downloadedConfig(page, button, expected) {
  const [download] = await Promise.all([page.waitForEvent('download'), button.click()]);
  assert.equal(await download.failure(), null);
  assert.match(download.suggestedFilename(), /^[a-z0-9-]{1,15}\.conf$/);
  const chunks = []; for await (const chunk of await download.createReadStream()) chunks.push(chunk);
  assert.equal(Buffer.concat(chunks).toString('utf8'), expected);
  return download.suggestedFilename();
}
(async () => {
  const browser = await chromium.launch({channel: 'chrome', headless: true});
  try {
    for (const state of cases) {
      const context = await browser.newContext({viewport: {width: state.width || 390, height: 844}, permissions: ['clipboard-read', 'clipboard-write']});
      const page = await context.newPage(), errors = [];
      page.on('pageerror', e => errors.push(e.message));
      await page.route('https://preview.test/**', async route => {
        const url = new URL(route.request().url());
        if (url.searchParams.has('raw')) {
          const text = state.lines.join('\n');
          return route.fulfill({status: state.error ? 502 : 200, contentType: 'text/plain',
            headers: {'Subscription-Userinfo': `upload=1073741824; download=2147483648; total=${state.unlimited ? 0 : 21474836480}; expire=${state.expired ? 1000 : 2000000000}`, 'X-TG3XBot-Client-Title': 'base64:' + Buffer.from('آزمایش وایرگارد').toString('base64')},
            body: state.base64 ? Buffer.from(text).toString('base64') : text});
        }
        if (url.pathname.startsWith('/tg3xbot-latency/')) return route.fulfill({status: 200, json: {metric: 'tcp_connect', server_time: Date.now()/1000, profiles: []}});
        let file;
        if (url.pathname.startsWith('/tg3xbot-assets/')) {
          const relative = url.pathname.split('/redesign-20260915-server-qr-v1/')[1];
          file = path.join(frontend, relative);
        } else file = path.join(frontend, 'index.html');
        if (!fs.existsSync(file)) return route.fulfill({status: 404, body: ''});
        const types = {'.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css', '.png': 'image/png', '.jpg': 'image/jpeg', '.woff2': 'font/woff2'};
        return route.fulfill({body: fs.readFileSync(file), contentType: types[path.extname(file)]});
      });
      const identifier = state.signed ? 'synthetic123.' + 'A'.repeat(43) : 'synthetic123';
      const canonical = 'https://preview.test/' + (state.signed ? 'sub/' : '') + identifier;
      await page.goto('https://preview.test/sub/' + identifier + '/');
      if (state.error) {
        await page.getByRole('button', {name: 'تلاش دوباره'}).waitFor();
      } else {
        await page.locator('#load-gate').waitFor({state: 'detached'});
        assert.equal(await page.locator('h1').textContent(), 'آزمایش وایرگارد');
        if (await page.locator('#t-servers').isVisible()) await page.locator('#t-servers').click();
        const serverToggle = page.locator('.server-toggle');
        if (await serverToggle.count() && await serverToggle.getAttribute('aria-expanded') !== 'true') await serverToggle.click();
        const expected = state.expired ? 1 : state.lines.length;
        assert.equal(await page.locator('.server').count(), expected);
        assert.equal(await page.getByRole('button', {name: /^دانلود فایل وایرگارد /}).count(), state.expired ? 0 : state.lines.filter(line => line.startsWith('wireguard://')).length);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, 'mobile overflow');
        if (!state.expired && state.lines.includes(finland)) {
          assert.equal(await page.locator('.server-protocol').count(), 2);
          const row = page.locator('.server').filter({hasText: 'Finland WireGuard Direct'});
          const firstName = await downloadedConfig(page, row.getByRole('button', {name: 'دانلود فایل وایرگارد Finland WireGuard Direct', exact: true}), expectedWG('finland'));
          const secondName = await downloadedConfig(page, page.getByRole('button', {name: 'دانلود فایل وایرگارد Turkey WireGuard Tunnel', exact: true}), expectedWG('turkey'));
          assert.notEqual(firstName, secondName, 'server filenames must be distinct');
          await row.getByRole('button', {name: 'کپی لینک Finland WireGuard Direct', exact: true}).click();
          assert.equal(await page.evaluate(() => navigator.clipboard.readText()), finland);
          await row.getByRole('button', {name: 'نمایش کد QR Finland WireGuard Direct', exact: true}).click();
          assert.equal(await page.locator('#qr-dialog').getAttribute('open'), '');
          await page.keyboard.press('Escape');
          await page.locator('#search').fill('Turkey');
          assert.equal(await page.locator('.server').count(), 1);
          await page.locator('#search').fill('');
          assert.equal(await page.locator('.server').count(), expected);
        }
        if (state.name === 'wg-dual-stack') {
          await downloadedConfig(page, page.getByRole('button', {name: /^دانلود فایل وایرگارد /}), expectedDualStack);
        }
        if (state.name === 'wg-invalid') {
          let downloads = 0; page.on('download', () => downloads++);
          await page.getByRole('button', {name: /^دانلود فایل وایرگارد /}).click();
          assert.equal(await page.locator('#toast').textContent(), 'فایل معتبر وایرگارد برای این سرور در دسترس نیست.');
          assert.equal(downloads, 0);
          const invalid = [
            finland.replace('publickey=', 'publickey=bad&unused='),
            finland.replace('address=', 'address=invalid&unused='),
            finland.replace('10.77.0.2', '999.77.0.2'),
            finland.replace('%2F32', '%2F33'),
            finland.replace('mtu=1280', 'mtu=65536'),
            finland.replace('mtu=1280', 'dns=1.1.1.1%0APostUp=bad'),
            finland.replace('mtu=1280', 'mtu=1280&MTU=1400'),
            finland.replace('mtu=1280', 'keepalive=-1'),
            finland.replace('mtu=1280', 'reserved=1,2,3'),
            finland.replace('mtu=1280', 'publicKey='+encodeURIComponent(publicKey)),
            finland.replace('mtu=1280', 'ip=10.77.0.3/32'),
            finland.replace(':443?', ':70000?'),
            finland.replace('@finland', ':password@finland'),
            dualStack.replace('%2F128', '%2F129'),
            'vless://invalid@example.test:443',
          ];
          assert.equal(await page.evaluate(values => values.every(raw => {try {wireguardConfig(raw);return false} catch {return true}}), invalid), true, 'invalid profiles must be rejected');
          assert.equal(await page.evaluate(raw => wireguardConfig(raw), finland.replace('&mtu=1280', '&keepalive=0&reserved=%5B0%2C0%2C0%5D')).then(text => text.endsWith('PersistentKeepalive = 0\n')), true);
        }
        await page.locator('#copy-sub').click();
        assert.equal(await page.evaluate(() => navigator.clipboard.readText()), canonical);
        if (state.signed) {
          if (await page.locator('#t-qr').isVisible()) await page.locator('#t-qr').click();
          await page.locator('#qr-open').click();
          assert.equal(await page.locator('#large-qr canvas').count(), 1);
          await page.keyboard.press('Escape');
        }
        assert.equal(await page.locator('body').textContent().then(text => text.includes('wireguard://')), false, 'raw credentials exposed in page text');
        if (state.name === 'mixed-base64') {
          const toggle = page.locator('.server-toggle');
          if (await toggle.count() && await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
          await page.waitForTimeout(550);
          fs.mkdirSync(path.join(root,'artifacts'),{recursive:true});
          await page.screenshot({path: path.join(root, 'artifacts/mobile.png'), fullPage: true});
        }
      }
      assert.deepEqual(errors, [], 'browser errors');
      console.log(state.name + ' PASS');
      await context.close();
    }
    console.log(cases.length + ' subscription browser scenarios passed; downloaded files matched expected profiles');
  } finally {await browser.close();}
})().catch(e => {console.error(e); process.exitCode = 1;});
