/* 飞洋海洋运输管理系统 · 页面层（12 页） */

var PAGES = {};

/* ---------- 工具 ---------- */
function pageHead(title, right) {
  return '<div class="page-hd"><h2>' + esc(title) + '</h2><div>' + (right || '') + '</div></div>';
}
function btn(id, text, cls) {
  return '<button id="' + id + '" class="btn ' + (cls || '') + '">' + esc(text) + '</button>';
}
function selOpts(list, valKey, nameFn, cur) {
  return list.map(function (x) {
    var v = typeof x === 'object' ? x[valKey] : x;
    var n = typeof x === 'object' ? nameFn(x) : x;
    return '<option value="' + esc(v) + '"' + (String(v) === String(cur) ? ' selected' : '') + '>' + esc(n) + '</option>';
  }).join('');
}
var CTYPES = ['20GP', '40GP', '40HQ', '20RF', '40RF', '45HC'];
var portCache = null, vesselCache = null, partnerCache = null;
function loadPorts() {
  return portCache ? Promise.resolve(portCache) :
    GET('/api/ports?size=200').then(function (r) { portCache = r.data.items; return portCache; });
}
function loadVessels() {
  return vesselCache ? Promise.resolve(vesselCache) :
    GET('/api/vessels?size=200').then(function (r) { vesselCache = r.data.items; return vesselCache; });
}
function loadPartners() {
  return partnerCache ? Promise.resolve(partnerCache) :
    GET('/api/partners?size=200').then(function (r) { partnerCache = r.data.items; return partnerCache; });
}

/* ---------- 工作台 ---------- */
PAGES.dash = function (main) {
  main.innerHTML = pageHead('工作台');
  return GET('/api/dashboard').then(function (r) {
    var d = r.data;
    main.innerHTML = pageHead('工作台') +
      '<div class="kpis">' +
      kpi(d.voyages_active, '在航航次') +
      kpi(d.voyages_month, '本月计划航次') +
      kpi(d.bookings_open, '进行中订舱') +
      kpi(d.containers_at_sea + ' 箱 / ' + d.teu_at_sea + ' TEU', '海上在途') +
      kpi(d.bls_draft, '草稿提单') +
      kpi(fmtCents(d.receivable_open_cents), '应收未结') +
      kpi(fmtCents(d.payable_open_cents), '应付未结') +
      kpi(fmtCents(d.demurrage_est_cents), '滞箱费预估', d.demurrage_est_cents > 0 ? 'warn' : '') +
      kpi(d.open_risks, '待处理风险', d.open_risks ? 'warn' : 'ok') +
      '</div>' +
      '<div class="card"><h3>快捷入口</h3><div class="quick">' +
      '<a href="#/voyage">航次调度</a><a href="#/booking">新建订舱</a><a href="#/bl">签发提单</a>' +
      '<a href="#/track">货物跟踪</a><a href="#/risk">风险扫描</a></div></div>';
  });
};

/* ---------- 船舶管理 ---------- */
PAGES.vessel = function (main) {
  var q = {};
  function refresh() {
    return GET('/api/vessels' + qs(q)).then(function (r) {
      var items = r.data.items;
      main.innerHTML = pageHead('船舶管理', btn('btn-add', '+ 新增船舶')) +
        '<div class="filter"><select id="f-vtype"><option value="">全部船型</option>' +
        selOpts(['container', 'bulk', 'tanker', 'roro'], null, null, q.vtype) + '</select></div>' +
        table(['编码', '船名', '~IMO', '船型', '~载重吨', '~箱位TEU', '船旗', '状态', ''], items, function (it) {
          return '<tr><td>' + esc(it.code) + '</td><td>' + esc(it.name) + '</td><td class="num">' + esc(it.imo) + '</td>' +
            '<td>' + vtypeTag(it.vtype) + '</td><td class="num">' + esc(it.dwt) + '</td><td class="num">' + esc(it.teu) + '</td>' +
            '<td>' + esc(it.flag || '—') + '</td><td>' + esc(it.status) + '</td>' +
            '<td>' + (perm('sea.vessels.write') ? '<button class="lnk" data-del="' + it.id + '">删除</button>' : '') + '</td></tr>';
        });
      document.getElementById('btn-add').onclick = function () { vesselForm(); };
      main.querySelectorAll('[data-del]').forEach(function (b) {
        b.onclick = function () {
          if (!confirm('确认删除该船舶？')) return;
          DEL('/api/vessels/' + b.getAttribute('data-del')).then(refresh).catch(function (e) { toast(e.message, true); });
        };
      });
      var sv = document.getElementById('f-vtype');
      if (sv) sv.onchange = function () { q.vtype = sv.value; refresh(); };
    });
  }
  function vesselForm() {
    modal('<h3>新增船舶</h3>' +
      field('编码', '<input id="v-code" placeholder="V004">') +
      field('船名', '<input id="v-name">') +
      field('IMO 号', '<input id="v-imo" placeholder="7 位数字">') +
      field('船型', '<select id="v-vtype">' + selOpts(['container', 'bulk', 'tanker', 'roro']) + '</select>') +
      field('载重吨', '<input id="v-dwt" type="number" value="0">') +
      field('箱位 TEU', '<input id="v-teu" type="number" value="0">') +
      field('船旗', '<input id="v-flag" placeholder="中国">') +
      '<div class="m-actions"><button class="btn" id="v-save">保存</button><button class="btn ghost" onclick="closeModal()">取消</button></div>');
    document.getElementById('v-save').onclick = function () {
      POST('/api/vessels', {
        code: document.getElementById('v-code').value.trim(),
        name: document.getElementById('v-name').value.trim(),
        imo: document.getElementById('v-imo').value.trim(),
        vtype: document.getElementById('v-vtype').value,
        dwt: Number(document.getElementById('v-dwt').value || 0),
        teu: Number(document.getElementById('v-teu').value || 0),
        flag: document.getElementById('v-flag').value.trim()
      }).then(function () { closeModal(); toast('已保存'); vesselCache = null; refresh(); })
        .catch(function (e) { toast(e.message, true); });
    };
  }
  return refresh();
};

/* ---------- 航次调度 ---------- */
PAGES.voyage = function (main) {
  var q = {};
  function refresh() {
    return Promise.all([GET('/api/voyages' + qs(q)), loadPorts(), loadVessels()]).then(function (rs) {
      var items = rs[0].data.items;
      main.innerHTML = pageHead('航次调度', btn('btn-add', '+ 新增航次')) +
        '<div class="filter"><select id="f-status"><option value="">全部状态</option>' +
        selOpts(['planned', 'departed', 'arrived', 'closed', 'cancelled'], null, null, q.status) + '</select>' +
        '<select id="f-month"><option value="">全部月份</option>' +
        selOpts([monthStr()], null, null, q.month) + '</select>' +
        btn('btn-export', '导出 CSV', 'ghost') + '</div>' +
        table(['航次号', '船舶', '航线', 'ETD', 'ETA', '~已载TEU', '~订舱箱量', '状态', ''], items, function (it) {
          var acts = '';
          if (perm('sea.voyages.write')) {
            if (it.status === 'planned') acts += '<button class="lnk" data-tr="' + it.id + '" data-act="to_departed">离港</button>' +
              '<button class="lnk" data-tr="' + it.id + '" data-act="to_cancelled">取消</button>';
            if (it.status === 'departed') acts += '<button class="lnk" data-tr="' + it.id + '" data-act="to_arrived">到港</button>';
            if (it.status === 'arrived') acts += '<button class="lnk" data-tr="' + it.id + '" data-act="to_closed">闭环</button>';
          }
          return '<tr><td>' + esc(it.no) + '</td><td>' + esc(it.vessel_name || '') + '</td>' +
            '<td>' + esc(it.pol) + ' → ' + esc(it.pod) + '</td><td>' + esc(it.etd || '—') + '</td><td>' + esc(it.eta || '—') + '</td>' +
            '<td class="num">' + Number(it.loaded_teu).toFixed(0) + '</td><td class="num">' + esc(it.boxes) + '</td>' +
            '<td>' + voyageTag(it.status) + '</td><td>' + acts + '</td></tr>';
        });
      document.getElementById('btn-add').onclick = function () { voyageForm(); };
      document.getElementById('btn-export').onclick = function () { dl('/api/export/voyages', 'voyages.csv'); };
      main.querySelectorAll('[data-tr]').forEach(function (b) {
        b.onclick = function () {
          POST('/api/voyages/' + b.getAttribute('data-tr') + '/transition', {action: b.getAttribute('data-act')})
            .then(function () { toast('已更新'); refresh(); })
            .catch(function (e) { toast(e.message, true); });
        };
      });
      var ss = document.getElementById('f-status');
      if (ss) ss.onchange = function () { q.status = ss.value; refresh(); };
      var sm = document.getElementById('f-month');
      if (sm) sm.onchange = function () { q.month = sm.value; refresh(); };
    });
  }
  function voyageForm() {
    modal('<h3>新增航次</h3>' +
      field('船舶', '<select id="vo-vessel">' + selOpts(vesselCache.filter(function (v) { return v.status === 'active'; }), 'id', function (v) { return v.name; }) + '</select>') +
      field('起运港', '<select id="vo-pol">' + selOpts(portCache, 'id', function (p) { return p.code + ' ' + p.name; }) + '</select>') +
      field('目的港', '<select id="vo-pod">' + selOpts(portCache, 'id', function (p) { return p.code + ' ' + p.name; }) + '</select>') +
      field('ETD', '<input id="vo-etd" type="date" value="' + todayStr() + '">') +
      field('ETA', '<input id="vo-eta" type="date">') +
      '<div class="m-actions"><button class="btn" id="vo-save">保存</button><button class="btn ghost" onclick="closeModal()">取消</button></div>');
    document.getElementById('vo-save').onclick = function () {
      POST('/api/voyages', {
        vessel_id: Number(document.getElementById('vo-vessel').value),
        pol_id: Number(document.getElementById('vo-pol').value),
        pod_id: Number(document.getElementById('vo-pod').value),
        etd: document.getElementById('vo-etd').value,
        eta: document.getElementById('vo-eta').value
      }).then(function () { closeModal(); toast('航次已创建'); refresh(); })
        .catch(function (e) { toast(e.message, true); });
    };
  }
  return refresh();
};

/* ---------- 订舱管理 ---------- */
PAGES.booking = function (main) {
  var q = {};
  function refresh() {
    return Promise.all([GET('/api/bookings' + qs(q)), loadVessels(), loadPartners()]).then(function (rs) {
      var items = rs[0].data.items;
      main.innerHTML = pageHead('订舱管理', btn('btn-add', '+ 新增订舱')) +
        '<div class="filter"><select id="f-status"><option value="">全部状态</option>' +
        selOpts(['booked', 'loaded', 'shipped', 'delivered', 'cancelled'], null, null, q.status) + '</select>' +
        btn('btn-export', '导出 CSV', 'ghost') + '</div>' +
        table(['订舱号', '航次', '托运人', '货物', '~箱数', '箱型', '~TEU', '状态', ''], items, function (it) {
          var acts = '';
          if (perm('sea.bookings.write')) {
            if (it.status === 'booked') acts += '<button class="lnk" data-tr="' + it.id + '" data-act="to_loaded">装船</button>' +
              '<button class="lnk" data-tr="' + it.id + '" data-act="to_cancelled">取消</button>';
            if (it.status === 'loaded') acts += '<button class="lnk" data-tr="' + it.id + '" data-act="to_shipped">开船</button>';
            if (it.status === 'shipped') acts += '<button class="lnk" data-tr="' + it.id + '" data-act="to_delivered">交付</button>';
          }
          return '<tr><td>' + esc(it.no) + '</td><td>' + esc(it.voyage_no || '') + '</td><td>' + esc(it.shipper_name || '') + '</td>' +
            '<td>' + esc(it.cargo_desc || '—') + '</td><td class="num">' + esc(it.boxes) + '</td><td>' + esc(it.ctype) + '</td>' +
            '<td class="num">' + Number(it.teu).toFixed(0) + '</td><td>' + bookingTag(it.status) + '</td><td>' + acts + '</td></tr>';
        });
      document.getElementById('btn-add').onclick = bookingForm;
      document.getElementById('btn-export').onclick = function () { dl('/api/export/bookings', 'bookings.csv'); };
      main.querySelectorAll('[data-tr]').forEach(function (b) {
        b.onclick = function () {
          POST('/api/bookings/' + b.getAttribute('data-tr') + '/transition', {action: b.getAttribute('data-act')})
            .then(function () { toast('已更新'); refresh(); })
            .catch(function (e) { toast(e.message, true); });
        };
      });
      var ss = document.getElementById('f-status');
      if (ss) ss.onchange = function () { q.status = ss.value; refresh(); };
    });
  }
  function bookingForm() {
    GET('/api/voyages?status=planned').then(function (r) {
      var vs = r.data.items;
      if (!vs.length) { toast('无计划中航次，请先建航次', true); return; }
      modal('<h3>新增订舱</h3>' +
        field('航次', '<select id="bk-voyage">' + selOpts(vs, 'id', function (v) { return v.no + ' ' + v.pol + '→' + v.pod; }) + '</select>') +
        field('托运人', '<select id="bk-shipper">' + selOpts(partnerCache, 'id', function (p) { return p.name; }) + '</select>') +
        field('收货人', '<input id="bk-consignee">') +
        field('货物描述', '<input id="bk-cargo">') +
        field('箱数', '<input id="bk-boxes" type="number" value="1" min="1">') +
        field('箱型', '<select id="bk-ctype">' + selOpts(CTYPES) + '</select>') +
        '<div class="m-actions"><button class="btn" id="bk-save">保存</button><button class="btn ghost" onclick="closeModal()">取消</button></div>');
      document.getElementById('bk-save').onclick = function () {
        POST('/api/bookings', {
          voyage_id: Number(document.getElementById('bk-voyage').value),
          shipper_id: Number(document.getElementById('bk-shipper').value),
          consignee: document.getElementById('bk-consignee').value.trim(),
          cargo_desc: document.getElementById('bk-cargo').value.trim(),
          boxes: Number(document.getElementById('bk-boxes').value || 1),
          ctype: document.getElementById('bk-ctype').value
        }).then(function () { closeModal(); toast('订舱已创建'); refresh(); })
          .catch(function (e) { toast(e.message, true); });
      };
    });
  }
  return refresh();
};

/* ---------- 提单管理 ---------- */
PAGES.bl = function (main) {
  var q = {};
  function refresh() {
    return GET('/api/bls' + qs(q)).then(function (r) {
      var items = r.data.items;
      main.innerHTML = pageHead('提单管理', btn('btn-add', '+ 新建提单')) +
        '<div class="filter"><select id="f-status"><option value="">全部状态</option>' +
        selOpts(['draft', 'issued', 'surrendered', 'telex_released'], null, null, q.status) + '</select></div>' +
        table(['提单号', '订舱号', '托运人', '收货人', '通知人', '~箱数', '状态', ''], items, function (it) {
          var acts = '';
          if (perm('sea.bls.write')) {
            if (it.status === 'draft') acts += '<button class="lnk" data-tr="' + it.id + '" data-act="to_issued">签发</button>';
            if (it.status === 'issued') acts += '<button class="lnk" data-tr="' + it.id + '" data-act="to_surrendered">交回</button>' +
              '<button class="lnk" data-tr="' + it.id + '" data-act="to_telex_released">电放</button>';
          }
          return '<tr><td>' + esc(it.no) + '</td><td>' + esc(it.booking_no || '') + '</td><td>' + esc(it.shipper || '—') + '</td>' +
            '<td>' + esc(it.consignee || '—') + '</td><td>' + esc(it.notify_party || '—') + '</td>' +
            '<td class="num">' + esc(it.boxes) + '</td><td>' + blTag(it.status) + '</td><td>' + acts + '</td></tr>';
        });
      document.getElementById('btn-add').onclick = blForm;
      main.querySelectorAll('[data-tr]').forEach(function (b) {
        b.onclick = function () {
          POST('/api/bls/' + b.getAttribute('data-tr') + '/transition', {action: b.getAttribute('data-act')})
            .then(function () { toast('已更新'); refresh(); })
            .catch(function (e) { toast(e.message, true); });
        };
      });
      var ss = document.getElementById('f-status');
      if (ss) ss.onchange = function () { q.status = ss.value; refresh(); };
    });
  }
  function blForm() {
    GET('/api/bookings?size=200').then(function (r) {
      var bs = r.data.items.filter(function (b) { return b.status !== 'cancelled'; });
      if (!bs.length) { toast('暂无可出提单的订舱', true); return; }
      modal('<h3>新建提单</h3>' +
        field('订舱', '<select id="bl-booking">' + selOpts(bs, 'id', function (b) { return b.no + ' ' + (b.cargo_desc || ''); }) + '</select>') +
        field('托运人', '<input id="bl-shipper">') +
        field('收货人', '<input id="bl-consignee">') +
        field('通知人', '<input id="bl-notify">') +
        field('箱数', '<input id="bl-boxes" type="number" value="1" min="1">') +
        '<div class="m-actions"><button class="btn" id="bl-save">保存</button><button class="btn ghost" onclick="closeModal()">取消</button></div>');
      document.getElementById('bl-save').onclick = function () {
        POST('/api/bls', {
          booking_id: Number(document.getElementById('bl-booking').value),
          shipper: document.getElementById('bl-shipper').value.trim(),
          consignee: document.getElementById('bl-consignee').value.trim(),
          notify_party: document.getElementById('bl-notify').value.trim(),
          boxes: Number(document.getElementById('bl-boxes').value || 1)
        }).then(function () { closeModal(); toast('提单已创建'); refresh(); })
          .catch(function (e) { toast(e.message, true); });
      };
    });
  }
  return refresh();
};

/* ---------- 箱货跟踪 ---------- */
PAGES.container = function (main) {
  var q = {};
  function refresh() {
    return GET('/api/containers' + qs(q)).then(function (r) {
      var items = r.data.items;
      main.innerHTML = pageHead('箱货跟踪', btn('btn-add', '+ 新增箱')) +
        '<div class="filter"><select id="f-status"><option value="">全部状态</option>' +
        selOpts(['empty', 'full', 'in_transit', 'unloaded', 'returned'], null, null, q.status) + '</select>' +
        '<select id="f-ctype"><option value="">全部箱型</option>' + selOpts(CTYPES, null, null, q.ctype) + '</select>' +
        btn('btn-export', '导出 CSV', 'ghost') + '</div>' +
        table(['箱号', '箱型', '封号', '~滞箱天数', '~滞箱费', '状态', ''], items, function (it) {
          var acts = '';
          if (perm('sea.containers.write')) {
            if (it.status === 'empty') acts += '<button class="lnk" data-tr="' + it.id + '" data-act="to_full">装货</button>';
            if (it.status === 'full') acts += '<button class="lnk" data-tr="' + it.id + '" data-act="to_in_transit">上船</button>' +
              '<button class="lnk" data-tr="' + it.id + '" data-act="to_returned">还箱</button>';
            if (it.status === 'in_transit') acts += '<button class="lnk" data-tr="' + it.id + '" data-act="to_unloaded">卸船</button>';
            if (it.status === 'unloaded') acts += '<button class="lnk" data-tr="' + it.id + '" data-act="to_returned">还箱</button>';
          }
          return '<tr><td>' + esc(it.container_no) + '</td><td>' + esc(it.ctype) + '</td><td>' + esc(it.seal_no || '—') + '</td>' +
            '<td class="num">' + (it.demurrage_days ? it.demurrage_days + ' 天' : '—') + '</td>' +
            '<td class="num">' + (it.demurrage_cents ? fmtCents(it.demurrage_cents) : '—') + '</td>' +
            '<td>' + containerTag(it.status) + '</td><td>' + acts + '</td></tr>';
        });
      document.getElementById('btn-add').onclick = ctnForm;
      document.getElementById('btn-export').onclick = function () { dl('/api/export/containers', 'containers.csv'); };
      main.querySelectorAll('[data-tr]').forEach(function (b) {
        b.onclick = function () {
          POST('/api/containers/' + b.getAttribute('data-tr') + '/transition', {action: b.getAttribute('data-act')})
            .then(function () { toast('已更新'); refresh(); })
            .catch(function (e) { toast(e.message, true); });
        };
      });
      var ss = document.getElementById('f-status');
      if (ss) ss.onchange = function () { q.status = ss.value; refresh(); };
      var sc = document.getElementById('f-ctype');
      if (sc) sc.onchange = function () { q.ctype = sc.value; refresh(); };
    });
  }
  function ctnForm() {
    GET('/api/bookings?size=200').then(function (r) {
      var bs = r.data.items.filter(function (b) { return b.status !== 'cancelled'; });
      modal('<h3>新增集装箱</h3>' +
        field('箱号（ISO 6346，11 位）', '<input id="ct-no" placeholder="TEMU3054388">') +
        field('箱型', '<select id="ct-ctype">' + selOpts(CTYPES) + '</select>') +
        field('封号', '<input id="ct-seal">') +
        field('关联订舱', '<select id="ct-booking"><option value="">不关联</option>' +
          selOpts(bs, 'id', function (b) { return b.no; }) + '</select>') +
        '<div class="m-actions"><button class="btn" id="ct-save">保存</button><button class="btn ghost" onclick="closeModal()">取消</button></div>');
      document.getElementById('ct-save').onclick = function () {
        POST('/api/containers', {
          container_no: document.getElementById('ct-no').value.trim(),
          ctype: document.getElementById('ct-ctype').value,
          seal_no: document.getElementById('ct-seal').value.trim(),
          booking_id: Number(document.getElementById('ct-booking').value) || null
        }).then(function () { closeModal(); toast('箱已建档'); refresh(); })
          .catch(function (e) { toast(e.message, true); });
      };
    });
  }
  return refresh();
};

/* ---------- 运价管理 ---------- */
PAGES.rate = function (main) {
  function refresh() {
    return Promise.all([GET('/api/rates?size=100'), loadPorts()]).then(function (rs) {
      var items = rs[0].data.items;
      main.innerHTML = pageHead('运价管理', btn('btn-add', '+ 新增运价') + ' ' + btn('btn-quote', '运价查询', 'ghost')) +
        table(['航线', '箱型', '~基础运价', '~附加费', '有效期', '状态', ''], items, function (it) {
          return '<tr><td>' + esc(it.lane) + '</td><td>' + esc(it.ctype) + '</td>' +
            '<td class="num">' + fmtCents(it.base_cents) + '</td><td class="num">' + fmtCents(it.surcharge_cents) + '</td>' +
            '<td>' + esc(it.valid_from) + ' ~ ' + esc(it.valid_to) + '</td>' +
            '<td>' + (it.expired ? tag('已过期', 'err') : tag('有效', 'ok')) + '</td><td></td></tr>';
        });
      document.getElementById('btn-add').onclick = rateForm;
      document.getElementById('btn-quote').onclick = quoteForm;
    });
  }
  function rateForm() {
    modal('<h3>新增运价</h3>' +
      field('起运港', '<select id="rt-pol">' + selOpts(portCache, 'id', function (p) { return p.code + ' ' + p.name; }) + '</select>') +
      field('目的港', '<select id="rt-pod">' + selOpts(portCache, 'id', function (p) { return p.code + ' ' + p.name; }) + '</select>') +
      field('箱型', '<select id="rt-ctype">' + selOpts(CTYPES) + '</select>') +
      field('基础运价（元）', '<input id="rt-base" type="number" value="20000">') +
      field('附加费（元）', '<input id="rt-sur" type="number" value="0">') +
      field('生效日', '<input id="rt-from" type="date" value="' + todayStr() + '">') +
      field('失效日', '<input id="rt-to" type="date" value="2026-12-31">') +
      '<div class="m-actions"><button class="btn" id="rt-save">保存</button><button class="btn ghost" onclick="closeModal()">取消</button></div>');
    document.getElementById('rt-save').onclick = function () {
      POST('/api/rates', {
        pol_id: Number(document.getElementById('rt-pol').value),
        pod_id: Number(document.getElementById('rt-pod').value),
        ctype: document.getElementById('rt-ctype').value,
        base_cents: yuan2cents('rt-base'),
        surcharge_cents: yuan2cents('rt-sur'),
        valid_from: document.getElementById('rt-from').value,
        valid_to: document.getElementById('rt-to').value
      }).then(function () { closeModal(); toast('运价已保存'); refresh(); })
        .catch(function (e) { toast(e.message, true); });
    };
  }
  function quoteForm() {
    modal('<h3>运价查询</h3>' +
      field('起运港', '<select id="qt-pol">' + selOpts(portCache, 'id', function (p) { return p.code + ' ' + p.name; }) + '</select>') +
      field('目的港', '<select id="qt-pod">' + selOpts(portCache, 'id', function (p) { return p.code + ' ' + p.name; }) + '</select>') +
      field('箱型', '<select id="qt-ctype">' + selOpts(CTYPES) + '</select>') +
      field('箱数', '<input id="qt-boxes" type="number" value="1" min="1">') +
      '<div class="m-actions"><button class="btn" id="qt-go">查询</button><button class="btn ghost" onclick="closeModal()">取消</button></div><div id="qt-out"></div>');
    document.getElementById('qt-go').onclick = function () {
      GET('/api/rates/quote' + qs({pol_id: document.getElementById('qt-pol').value,
        pod_id: document.getElementById('qt-pod').value,
        ctype: document.getElementById('qt-ctype').value,
        boxes: document.getElementById('qt-boxes').value}))
        .then(function (r) {
          var d = r.data;
          document.getElementById('qt-out').innerHTML = '<div class="quote">' +
            '合计：<b>' + fmtCents(d.total_cents) + '</b>（基础 ' + fmtCents(d.base_cents) + ' + 附加 ' +
            fmtCents(d.surcharge_cents) + '）× TEU ' + d.unit_teu + ' × ' + d.boxes + ' 箱</div>';
        }).catch(function (e) { document.getElementById('qt-out').innerHTML = '<div class="empty">' + esc(e.message) + '</div>'; });
    };
  }
  return refresh();
};

/* ---------- 客户管理 ---------- */
PAGES.partner = function (main) {
  var q = {};
  function refresh() {
    return GET('/api/partners' + qs(q)).then(function (r) {
      var items = r.data.items;
      main.innerHTML = pageHead('客户管理', btn('btn-add', '+ 新增')) +
        '<div class="filter"><select id="f-ptype"><option value="">全部类型</option>' +
        selOpts(['customer', 'agent', 'supplier', 'both'], null, null, q.ptype) + '</select></div>' +
        table(['编码', '名称', '类型', '联系人', '电话', '~应收未结', '~应付未结', '~信用额度', ''], items, function (it) {
          return '<tr><td>' + esc(it.code) + '</td><td>' + esc(it.name) + '</td><td>' + ptypeTag(it.ptype) + '</td>' +
            '<td>' + esc(it.contact || '—') + '</td><td>' + esc(it.phone || '—') + '</td>' +
            '<td class="num">' + fmtCents(it.receivable_cents) + '</td><td class="num">' + fmtCents(it.payable_cents) + '</td>' +
            '<td class="num">' + fmtCents(it.credit_limit_cents) + '</td>' +
            '<td>' + (perm('sea.partners.write') ? '<button class="lnk" data-del="' + it.id + '">删除</button>' : '') + '</td></tr>';
        });
      document.getElementById('btn-add').onclick = pForm;
      main.querySelectorAll('[data-del]').forEach(function (b) {
        b.onclick = function () {
          if (!confirm('确认删除该客户？')) return;
          DEL('/api/partners/' + b.getAttribute('data-del')).then(refresh).catch(function (e) { toast(e.message, true); });
        };
      });
      var sp = document.getElementById('f-ptype');
      if (sp) sp.onchange = function () { q.ptype = sp.value; refresh(); };
    });
  }
  function pForm() {
    modal('<h3>新增客户</h3>' +
      field('名称', '<input id="pt-name">') +
      field('类型', '<select id="pt-ptype">' + selOpts(['customer', 'agent', 'supplier', 'both']) + '</select>') +
      field('联系人', '<input id="pt-contact">') +
      field('电话', '<input id="pt-phone">') +
      field('信用额度（元）', '<input id="pt-credit" type="number" value="0">') +
      '<div class="m-actions"><button class="btn" id="pt-save">保存</button><button class="btn ghost" onclick="closeModal()">取消</button></div>');
    document.getElementById('pt-save').onclick = function () {
      POST('/api/partners', {
        name: document.getElementById('pt-name').value.trim(),
        ptype: document.getElementById('pt-ptype').value,
        contact: document.getElementById('pt-contact').value.trim(),
        phone: document.getElementById('pt-phone').value.trim(),
        credit_limit_cents: yuan2cents('pt-credit')
      }).then(function () { closeModal(); toast('已保存'); partnerCache = null; refresh(); })
        .catch(function (e) { toast(e.message, true); });
    };
  }
  return refresh();
};

/* ---------- 应收应付 ---------- */
PAGES.bill = function (main) {
  var q = {};
  function refresh() {
    return GET('/api/bills' + qs(q)).then(function (r) {
      var items = r.data.items;
      main.innerHTML = pageHead('应收应付', btn('btn-add', '+ 新增账单')) +
        '<div class="filter"><select id="f-btype"><option value="">全部类型</option>' +
        selOpts(['receivable', 'payable', 'demurrage'], null, null, q.btype) + '</select>' +
        '<label class="chk"><input type="checkbox" id="f-overdue"> 仅看逾期</label>' +
        btn('btn-export', '导出 CSV', 'ghost') + '</div>' +
        table(['单号', '类型', '~金额', '~未结', '~逾期天数', '账龄', '到期日', '状态', ''], items, function (it) {
          var acts = '';
          if (perm('sea.bills.write') && it.status !== 'settled') acts += '<button class="lnk" data-settle="' + it.id + '">结算</button>';
          return '<tr><td>' + esc(it.no) + '</td><td>' + btypeTag(it.btype) + '</td>' +
            '<td class="num">' + fmtCents(it.amount_cents) + '</td><td class="num">' + fmtCents(it.remaining_cents) + '</td>' +
            '<td class="num">' + (it.days_overdue || '—') + '</td><td>' + (it.aging ? esc(it.aging) : '—') + '</td>' +
            '<td>' + esc(it.due_date || '—') + '</td><td>' + billTag(it.status) + '</td><td>' + acts + '</td></tr>';
        });
      document.getElementById('btn-add').onclick = bForm;
      document.getElementById('btn-export').onclick = function () { dl('/api/export/bills', 'bills.csv'); };
      main.querySelectorAll('[data-settle]').forEach(function (b) {
        b.onclick = function () { settleForm(Number(b.getAttribute('data-settle'))); };
      });
      var sb = document.getElementById('f-btype');
      if (sb) sb.onchange = function () { q.btype = sb.value; refresh(); };
      var so = document.getElementById('f-overdue');
      if (so) so.onchange = function () { q.overdue = so.checked ? '1' : ''; refresh(); };
    });
  }
  function settleForm(bid) {
    GET('/api/bills/' + bid).then(function (r) {
      var d = r.data;
      modal('<h3>结算 ' + esc(d.no) + '</h3>' +
        field('未结金额（元）', '<input value="' + (d.remaining_cents / 100).toFixed(2) + '" disabled>') +
        field('本次结算（元）', '<input id="st-amt" type="number" value="' + (d.remaining_cents / 100).toFixed(2) + '">') +
        field('方式', '<select id="st-method"><option value="bank">银行</option><option value="cash">现金</option><option value="offset">冲抵</option></select>') +
        '<div class="m-actions"><button class="btn" id="st-go">确认结算</button><button class="btn ghost" onclick="closeModal()">取消</button></div>');
      document.getElementById('st-go').onclick = function () {
        POST('/api/bills/' + bid + '/settle', {
          amount_cents: yuan2cents('st-amt'),
          method: document.getElementById('st-method').value
        }).then(function (x) { closeModal(); toast('已结算 ' + fmtCents(x.data.settled_cents)); refresh(); })
          .catch(function (e) { toast(e.message, true); });
      };
    });
  }
  function bForm() {
    loadPartners().then(function () {
      modal('<h3>新增账单</h3>' +
        field('类型', '<select id="bd-btype"><option value="receivable">应收运费</option><option value="demurrage">滞箱费</option><option value="payable">应付</option></select>') +
        field('客户', '<select id="bd-partner">' + selOpts(partnerCache, 'id', function (p) { return p.name; }) + '</select>') +
        field('金额（元）', '<input id="bd-amt" type="number">') +
        field('到期日', '<input id="bd-due" type="date">') +
        field('摘要', '<input id="bd-ref">') +
        '<div class="m-actions"><button class="btn" id="bd-save">保存</button><button class="btn ghost" onclick="closeModal()">取消</button></div>');
      document.getElementById('bd-save').onclick = function () {
        POST('/api/bills', {
          btype: document.getElementById('bd-btype').value,
          partner_id: Number(document.getElementById('bd-partner').value),
          amount_cents: yuan2cents('bd-amt'),
          due_date: document.getElementById('bd-due').value,
          ref: document.getElementById('bd-ref').value.trim()
        }).then(function () { closeModal(); toast('账单已创建'); refresh(); })
          .catch(function (e) { toast(e.message, true); });
      };
    });
  }
  return refresh();
};

/* ---------- 全链路跟踪 ---------- */
PAGES.track = function (main) {
  main.innerHTML = pageHead('全链路跟踪') +
    '<div class="card"><p style="color:#5a6b7d;font-size:13px;margin:0 0 10px">输入订舱号、提单号或集装箱箱号，即可查看从订舱、装船到卸箱还箱的全链路时间线。</p><div class="filter"><input id="tk-no" placeholder="输入订舱号 / 提单号 / 箱号，如 BK20260101-002" style="flex:1">' +
    btn('tk-go', '跟踪', '') + '</div><div id="tk-out"></div></div>';
  function doTrack() {
    var no = document.getElementById('tk-no').value.trim();
    if (!no) return;
    GET('/api/track/' + encodeURIComponent(no)).then(function (r) {
      document.getElementById('tk-out').innerHTML = '<h3>' + esc(r.data.query) + '</h3><ul class="timeline">' +
        r.data.events.map(function (e) {
          return '<li><i></i><b>' + esc(e.ts || '') + '</b><span>' + esc(e.what) + '</span></li>';
        }).join('') + '</ul>';
    }).catch(function (e) {
      document.getElementById('tk-out').innerHTML = '<div class="empty">' + esc(e.message) + '</div>';
    });
  }
  document.getElementById('tk-go').onclick = doTrack;
  document.getElementById('tk-no').addEventListener('keydown', function (e) { if (e.key === 'Enter') doTrack(); });
};

/* ---------- 风险预警 ---------- */
PAGES.risk = function (main) {
  var q = {};
  function refresh() {
    return GET('/api/risks' + qs(q)).then(function (r) {
      var items = r.data.items;
      main.innerHTML = pageHead('风险预警', (perm('sea.risk.write') ? btn('btn-scan', '立即扫描') : '')) +
        '<div class="filter"><select id="f-status"><option value="">全部状态</option>' +
        selOpts(['open', 'resolved'], null, null, q.status) + '</select></div>' +
        table(['类型', '标题', '详情', '~分值', '级别', '状态', ''], items, function (it) {
          var acts = '';
          if (perm('sea.risk.write') && it.status === 'open') acts += '<button class="lnk" data-res="' + it.id + '">处理</button>';
          return '<tr><td>' + esc(it.rtype) + '</td><td>' + esc(it.title) + '</td><td>' + esc(it.detail) + '</td>' +
            '<td class="num">' + esc(it.score) + '</td><td>' + levelTag(it.grade) + '</td>' +
            '<td>' + (it.status === 'open' ? tag('待处理', 'warn') : tag('已处理', 'ok')) + '</td><td>' + acts + '</td></tr>';
        });
      var bs = document.getElementById('btn-scan');
      if (bs) bs.onclick = function () {
        POST('/api/risks/scan').then(function (x) {
          toast('扫描完成，新增 ' + x.data.created + ' 条');
          refresh();
        }).catch(function (e) { toast(e.message, true); });
      };
      main.querySelectorAll('[data-res]').forEach(function (b) {
        b.onclick = function () {
          PUT('/api/risks/' + b.getAttribute('data-res') + '/resolve', {note: '已人工处理'})
            .then(function () { toast('已处理'); refresh(); })
            .catch(function (e) { toast(e.message, true); });
        };
      });
      var ss = document.getElementById('f-status');
      if (ss) ss.onchange = function () { q.status = ss.value; refresh(); };
    });
  }
  return refresh();
};

/* ---------- 系统管理 ---------- */
PAGES.system = function (main) {
  return Promise.all([GET('/api/me'), GET('/api/rules'), GET('/api/notices')]).then(function (rs) {
    var me = rs[0].data, rules = rs[1].data.items, notices = rs[2].data.items;
    var isAdmin = me.user.role === 'admin';
    main.innerHTML = pageHead('系统管理') +
      '<div class="card"><h3>业务参数</h3>' +
      table(['参数', '值', '说明'], [
        {k: 'free_days', v: rules.filter(function (r) { return r.name === 'free_days'; })[0], d: '免箱期（天）'},
        {k: 'demurrage_rate_cents', v: rules.filter(function (r) { return r.name === 'demurrage_rate_cents'; })[0], d: '滞箱费率（分/天）'},
        {k: 'company', v: rules.filter(function (r) { return r.name === 'company'; })[0], d: '公司名称'}
      ], function (it) {
        return '<tr><td>' + esc(it.k) + '</td><td>' + esc(it.v ? it.v.value : '—') + '</td><td>' + esc(it.d) + '</td></tr>';
      }) + '</div>' +
      '<div class="card"><h3>公告</h3>' + notices.map(function (n) {
        return '<div class="notice"><b>' + esc(n.title) + '</b><p>' + esc(n.content) + '</p></div>';
      }).join('') + '</div>' +
      '<div class="card"><h3>我的权限</h3><div class="perms">' +
      (me.perms === '*' ? ['* 全部权限'] : me.perms).map(function (p) { return tag(p, ''); }).join(' ') + '</div></div>' +
      (isAdmin ? '<div class="card"><h3>API Key（对接 ERP / 货代平台）</h3><div id="keys">加载中…</div>' +
        '<div class="m-actions">' + btn('key-add', '+ 生成 API Key') + '</div></div>' : '');
    if (isAdmin) {
      GET('/api/api-keys').then(function (r) {
        document.getElementById('keys').innerHTML = table(['名称', '前缀', '权限', '状态', '最近使用'], r.data.items, function (it) {
          return '<tr><td>' + esc(it.name) + '</td><td>' + esc(it.prefix) + '</td><td>' + esc(it.perms) + '</td>' +
            '<td>' + (it.status ? tag('启用', 'ok') : tag('停用', 'err')) + '</td><td>' + esc(it.last_used || '—') + '</td></tr>';
        });
      });
      document.getElementById('key-add').onclick = function () {
        modal('<h3>生成 API Key</h3>' +
          field('名称', '<input id="ak-name" placeholder="erp">') +
          field('权限', '<input id="ak-perms" value="sea.*">') +
          '<div class="m-actions"><button class="btn" id="ak-go">生成</button><button class="btn ghost" onclick="closeModal()">取消</button></div><div id="ak-out"></div>');
        document.getElementById('ak-go').onclick = function () {
          POST('/api/api-keys', {name: document.getElementById('ak-name').value.trim() || 'default',
            perms: document.getElementById('ak-perms').value.trim() || 'sea.*'})
            .then(function (r) {
              document.getElementById('ak-out').innerHTML = '<div class="quote">Key：<b>' + esc(r.data.key) + '</b>（仅此一次展示）</div>';
            }).catch(function (e) { toast(e.message, true); });
        };
      };
    }
  });
};
