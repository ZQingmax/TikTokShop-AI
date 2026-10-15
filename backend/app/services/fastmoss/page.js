// Operations run in the authenticated FastMoss ranking page; no arbitrary caller JavaScript.
// Structure verified against https://www.fastmoss.com/zh/e-commerce/newProducts (2026-10-14):
// - 国家、品类、店铺类型均为 Ant Design 单选组；国家 value = 地区代码（MY），品类 value = c_code（10 = 居家日用）
// - 页面数据请求 /api/goods/newProduct?...&region=MY&l1_cid=10&page=N 反映实际生效的筛选
// - 表格首行是隐藏的 ant-table-measure-row；前三名排名为奖牌图标（无文字）
const text = e => (e.innerText || e.textContent || '').trim();
const labelOf = r => text(r.closest('label') || r.parentElement);
const radioGroups = () => {
  const groups = {};
  for (const r of document.querySelectorAll('input[type="radio"]')) (groups[r.name] ||= []).push(r);
  return Object.values(groups);
};
// 国家组：含 value=地区代码 的组；品类组：同一组内 value=分类标识 且显示名一致（避免与店铺类型 1/2 混淆）
const findRadio = (value, label) => {
  for (const group of radioGroups()) {
    const match = group.find(r => r.value === String(value) && labelOf(r) === label);
    if (match) return {radio: match, group};
  }
  return null;
};
// 实测：页面埋点请求很多，浏览器默认 250 条资源计时缓冲很快写满，之后的数据请求不再出现在
// performance.getEntries 中。首次操作时注册观察器单独记录榜单数据请求，并放宽缓冲上限。
const isData = u => u.includes('/api/goods/newProduct');
const dataRequests = () => {
  if (!window.__fmDataRequests) {
    window.__fmDataRequests = performance.getEntriesByType('resource').map(e => e.name).filter(isData);
    try { performance.setResourceTimingBufferSize(100000); } catch (e) { /* 旧浏览器忽略 */ }
    new PerformanceObserver(list => {
      for (const entry of list.getEntries()) if (isData(entry.name)) window.__fmDataRequests.push(entry.name);
    }).observe({type: 'resource'});
  }
  return window.__fmDataRequests.slice();
};
dataRequests();
const params = url => Object.fromEntries(new URL(url, location.origin).searchParams.entries());

if (location.hostname !== 'www.fastmoss.com' && location.hostname !== 'fastmoss.com')
  return {error: '浏览器未停留在 FastMoss 页面'};
if (/login|signin/i.test(location.pathname)) return {error: '请先在浏览器登录 FastMoss'};

if (operation === 'catalog') {
  // 页面自身的品类筛选项即该榜单真实分类树（当前仅一级品类）
  const countries = [], categories = [];
  for (const group of radioGroups()) {
    const options = group.map(r => ({value: r.value, label: labelOf(r)})).filter(o => o.label && o.value && o.value !== 'all');
    if (options.some(o => /^[A-Z]{2}$/.test(o.value)) && options.every(o => /^[A-Z]{2}$/.test(o.value))) countries.push(...options);
    else if (options.length >= 10 && options.every(o => /^\d+$/.test(o.value))) categories.push(...options);
  }
  if (!countries.length || !categories.length) return {error: '榜单页面没有国家或品类筛选项，请检查登录、权限或页面结构'};
  return {countries, categories};
}

if (operation === 'select') {
  const found = findRadio(args.value, args.label);
  if (!found) return {error: `页面找不到筛选项：${args.label}（${args.value}）`};
  if (!found.radio.checked) (found.radio.closest('label') || found.radio).click();
  return {clicked: true, requests: dataRequests().length};
}

if (operation === 'verify') {
  // 两层确认：单选框已选中，且最新一次页面数据请求带有相同的地区、品类与页码
  const country = findRadio(args.country, args.country_label);
  const category = findRadio(args.category_id, args.category_label);
  const latest = dataRequests().pop();
  const p = latest ? params(latest) : {};
  return {
    country: !!country?.radio.checked && p.region === args.country,
    category: !!category?.radio.checked && p.l1_cid === String(args.category_id),
    page: p.page === String(args.page),
    request: latest ? {region: p.region || null, l1_cid: p.l1_cid || null, page: p.page || null,
                       start_date: p.start_date || null, end_date: p.end_date || null, rank_type: p.rank_type || null} : null,
  };
}

if (operation === 'extract') {
  const tables = [...document.querySelectorAll('table')].filter(e => e.getClientRects().length);
  const table = tables[tables.length - 1];
  if (!table) return {error: '没有商品表格；请检查登录、榜单访问权限或页面结构'};
  if (document.querySelector('.ant-spin-spinning,[aria-busy="true"]')) return {loading: true};
  // 页面明确显示“暂无数据”（Ant Design 空表占位行），与表格结构变化区分开
  if (table.querySelector('tr.ant-table-placeholder .ant-empty, tr.ant-table-placeholder') && !table.querySelector('tbody tr.ant-table-row'))
    return {rows: [], empty: true, source_url: location.href};
  const headers = [...table.querySelectorAll('thead th')].map(text);
  const rows = [...table.querySelectorAll('tbody tr.ant-table-row')].map((tr, index) => {
    const cells = [...tr.querySelectorAll('td')];
    const product = cells[1];
    const link = product?.querySelector('a[href*="/e-commerce/detail/"]');
    const shopLink = cells[3]?.querySelector('a[href*="/shop-marketing/detail/"]');
    const image = product?.querySelector('img');
    // 前三名是奖牌图标：记录“无文字”，由后端按页面顺序补排名并标注来源
    return {cells: cells.map(text), position: index + 1, rank_icon: !text(cells[0] || document.createElement('td')) && !!cells[0]?.querySelector('svg,img'),
            product_url: link?.href || '', shop_url: shopLink?.href || '', image_url: image?.currentSrc || image?.src || ''};
  }).filter(r => r.cells.length >= 10 && r.cells[1]);
  const latest = dataRequests().pop();
  const p = latest ? params(latest) : {};
  // 统计口径：表头“三日销量”→“三日”；统计日期取日期选择器（页面实际值），不使用今天的日期
  const salesHeader = headers.find(h => /销量$/.test(h) && !/^总/.test(h)) || '';
  const dates = [...document.querySelectorAll('.ant-picker input')].map(e => e.value).filter(v => /^\d{4}-\d{2}-\d{2}$/.test(v));
  return {rows, headers, source_url: location.href, period: salesHeader.replace(/销量$/, '') || null,
          stat_start: dates[0] || p.start_date || null, stat_end: dates[dates.length - 1] || p.end_date || null,
          page_size: Number(p.pagesize) || null};
}

if (operation === 'next') {
  const button = [...document.querySelectorAll('li[title="下一页"],li.ant-pagination-next')].find(e => e.getClientRects().length);
  if (!button || button.classList.contains('ant-pagination-disabled') || button.getAttribute('aria-disabled') === 'true')
    return {clicked: false};
  // 实测：分页按钮只响应完整的指针/鼠标事件序列，单独 .click() 不会翻页
  const target = button.querySelector('button') || button;
  for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'])
    target.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, view: window}));
  return {clicked: true};
}
return {error: '未知页面操作'};
