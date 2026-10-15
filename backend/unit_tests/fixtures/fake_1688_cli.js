// 测试专用的假 1688 CLI：不联网、不启动浏览器。根据 FAKE_1688_MODE 环境变量模拟 CLI 行为。
// 输出约定与 1688-cli 一致：成功 JSON → stdout；失败 {"ok":false,...} → stderr，非 0 退出码。
const mode = process.env.FAKE_1688_MODE || 'search';
const args = process.argv.slice(2);
const out = (v) => process.stdout.write(JSON.stringify(v) + '\n');
const fail = (code, exit, details = {}) => {
  process.stderr.write('Update available: 9.9.9\n');
  process.stderr.write(JSON.stringify({ ok: false, code, message: 'TEST_ONLY', details }) + '\n');
  process.exit(exit);
};
if (mode === 'echo-args') { out({ offers: [], argv: args }); process.exit(0); }
if (mode === 'not-logged-in') fail('NOT_LOGGED_IN', 3, { currentUrl: 'https://login.example.test/?token=SECRET_TEST_TOKEN', failureKind: 'not_logged_in' });
if (mode === 'risk') fail('RISK_CONTROL', 4, { pageState: 'risk_control' });
if (mode === 'paused') fail('DAEMON_PAUSED', 9, { failureKind: 'not_logged_in', pausedUntil: '2026-01-01T00:00:00Z' });
if (mode === 'garbage') { process.stdout.write('not json at all'); process.exit(0); }
if (mode === 'hang') { setTimeout(() => out({ offers: [] }), 60000); }
else {
  out({ keyword: 'TEST_ONLY', total: 1, offers: [{ offerId: '700000000001', title: 'TEST_ONLY 露营灯', url: 'https://detail.1688.com/offer/700000000001.html',
    price: { text: '¥10.5', min: 10.5, max: 12 }, supplier: { name: 'TEST_ONLY 供应商', shopUrl: 'https://shop-test.1688.com', years: 3 },
    image: 'https://img.example.test/a.jpg,https://img.example.test/b.jpg', isP4P: false }] });
}
