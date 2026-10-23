/* 飞洋海洋运输管理系统 · 手机APP（PWA）*/
'use strict';
var BASE = location.href.replace(/\/m\/[^\/]*$/, '/').replace(/\/m$/, '/');
if (location.pathname.indexOf('/m/') < 0) BASE = location.origin + '/ocean/';
var TOKEN = localStorage.getItem('feiyang_m_token') || '';
var ME = null;
var TAGS = {planned:'计划', departed:'已离港', arrived:'已到港', closed:'已闭环', cancelled:'已取消',
  booked:'已订舱', loaded:'已装船', shipped:'运输中', delivered:'已交付',
  empty:'空箱', full:'重箱', in_transit:'在途', unloaded:'已卸货', returned:'已返空',
  draft:'草稿', issued:'已签发', surrendered:'已交单', telex_released:'电放',
  receivable:'应收', payable:'应付'};

function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
function yuan(c){return (Number(c||0)/100).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});}
function toast(m){var t=document.getElementById('toast');t.textContent=m;t.classList.add('show');setTimeout(function(){t.classList.remove('show');},2200);}
function tag(s){return '<span class="tag s-'+esc(s)+'">'+(TAGS[s]||esc(s))+'</span>';}

function api(path, opt){
  opt = opt || {};
  opt.headers = Object.assign({'Content-Type':'application/json'}, opt.headers||{},
    TOKEN?{'Authorization':'Bearer '+TOKEN}:{});
  if (opt.body && typeof opt.body !== 'string') opt.body = JSON.stringify(opt.body);
  return fetch(BASE.replace(/\/$/,'') + path, opt).then(function(r){
    return r.json().then(function(j){
      if (j.code !== 200) throw new Error(j.message || ('HTTP '+r.status));
      return j.data;
    });
  });
}

/* ---------- 页面 ---------- */
var TABS = {};
TABS.dash = function(){
  return api('/api/dashboard').then(function(d){
    var k = d || {};
    function item(l,v){return '<div class="kpi"><b>'+v+'</b><span>'+l+'</span></div>';}
    return api('/api/notices').then(function(ns){
      var notice = (ns && ns.items && ns.items[0]) ? '<div class="notice">📢 '+esc(ns.items[0].title||ns.items[0].content||'')+'</div>' : '';
      return notice + '<div class="kpis">'
        + item('在航航次', (k.active_voyages!=null?k.active_voyages:(k.voyages_active||0)))
        + item('在途箱量', (k.containers_transit!=null?k.containers_transit:(k.containers_in_transit||0)))
        + item('未交订舱', (k.bookings_open!=null?k.bookings_open:(k.bookings_pending||0)))
        + item('应收余额(元)', yuan(k.receivable_cents!=null?k.receivable_cents:k.receivable))
        + item('逾期账单', (k.bills_overdue!=null?k.bills_overdue:(k.overdue_bills||0)))
        + item('滞箱费预估(元)', yuan(k.demurrage_cents!=null?k.demurrage_cents:k.demurr))
        + '</div>' + (k.notices? '':'');
    });
  }).catch(function(e){return errHtml(e);});
};
TABS.voyage = function(){
  return api('/api/voyages').then(function(d){
    var items = (d && d.items) || d || [];
    if (!items.length) return '<div class="empty">暂无航次</div>';
    return items.map(function(v){
      return '<div class="card"><h4>'+esc(v.voyage_no||v.no||('航次#'+v.id))+' '+tag(v.status)+'</h4>'
        + '<div class="row"><span class="lb">船舶</span><span>'+esc(v.vessel_name||v.vessel||'-')+'</span></div>'
        + '<div class="row"><span class="lb">航线</span><span>'+esc(v.route||((v.pol||'-')+' → '+(v.pod||'-')))+'</span></div>'
        + '<div class="row"><span class="lb">ETD / ETA</span><span>'+esc(v.etd||'-')+' / '+esc(v.eta||'-')+'</span></div>'
        + '</div>';
    }).join('');
  }).catch(function(e){return errHtml(e);});
};
TABS.booking = function(){
  return api('/api/bookings').then(function(d){
    var items = (d && d.items) || d || [];
    if (!items.length) return '<div class="empty">暂无订舱</div>';
    return items.map(function(b){
      return '<div class="card"><h4>'+esc(b.booking_no||b.no||('订舱#'+b.id))+' '+tag(b.status)+'</h4>'
        + '<div class="row"><span class="lb">客户</span><span>'+esc(b.shipper_name||b.shipper||'-')+'</span></div>'
        + '<div class="row"><span class="lb">箱型箱量</span><span>'+esc(b.ctype||'-')+' × '+esc(b.boxes!=null?b.boxes:'-')+'</span></div>'
        + '<div class="row"><span class="lb">航次</span><span>'+esc(b.voyage_no||b.voyage||'-')+'</span></div>'
        + '</div>';
    }).join('');
  }).catch(function(e){return errHtml(e);});
};
TABS.container = function(){
  return api('/api/containers').then(function(d){
    var items = (d && d.items) || d || [];
    if (!items.length) return '<div class="empty">暂无箱货</div>';
    return items.map(function(c){
      return '<div class="card"><h4>'+esc(c.container_no||c.no)+'</h4>'+tag(c.status)
        + '<div class="row"><span class="lb">箱型 / 封号</span><span>'+esc(c.ctype||'-')+' / '+esc(c.seal_no||'-')+'</span></div>'
        + '<div class="row"><span class="lb">订舱</span><span>'+esc(c.booking_no||c.booking||'-')+'</span></div>'
        + (c.unloaded_at?'<div class="row"><span class="lb">卸箱时间</span><span>'+esc(c.unloaded_at)+'</span></div>':'')
        + '</div>';
    }).join('');
  }).catch(function(e){return errHtml(e);});
};
TABS.me = function(){
  return api('/api/me').then(function(d){
    ME = d;
    var u = (d && d.user) || {};
    return '<div class="me-card"><b>'+esc(u.name||'-')+'</b><p>'+esc(u.role||'-')+' · '+esc(u.username||'')+'</p></div>'
      + '<div class="me-item">权限数量<span>'+((d&&d.perms)||[]).length+'</span></div>'
      + '<div class="me-item">系统版本<span>飞洋OTMS V1.0</span></div>'
      + '<div class="me-item">服务地址<span style="max-width:60%;overflow:hidden;text-overflow:ellipsis">'+esc(BASE)+'</span></div>'
      + '<button class="btn gray" onclick="logout()">退出登录</button>';
  }).catch(function(e){return errHtml(e);});
};
function errHtml(e){
  if (String(e.message||e).indexOf('401')>=0 || String(e.message||e).indexOf('未登录')>=0 || String(e.message||e).indexOf('token')>=0) return '';
  return '<div class="empty">加载失败：'+esc(e.message||e)+'</div>';
}

/* ---------- 路由 ---------- */
var cur = 'dash';
function render(tab){
  cur = tab;
  var names = {dash:'工作台', voyage:'航次管理', booking:'订舱管理', container:'箱货管理', me:'我的'};
  document.getElementById('hd-title').textContent = names[tab] || '飞洋OTMS';
  document.querySelectorAll('#tabbar a').forEach(function(a){
    a.classList.toggle('on', a.getAttribute('data-tab') === tab);
  });
  var main = document.getElementById('main');
  main.innerHTML = '<div class="empty">加载中…</div>';
  (TABS[tab] || TABS.dash)().then(function(html){
    if (cur === tab) main.innerHTML = html || '<div class="empty">暂无数据</div>';
  }).catch(function(e){ if (cur===tab) main.innerHTML = errHtml(e); });
}
document.getElementById('tabbar').addEventListener('click', function(ev){
  var a = ev.target.closest('a'); if (!a) return;
  render(a.getAttribute('data-tab'));
});

function showLogin(){
  document.getElementById('main').innerHTML =
    '<div class="card"><h4>登录飞洋OTMS</h4>'
    + '<input id="lg-u" class="search" style="width:100%;margin:8px 0" placeholder="用户名">'
    + '<input id="lg-p" class="search" type="password" style="width:100%;margin:8px 0" placeholder="密码">'
    + '<button class="btn" onclick="doLogin()">登 录</button></div>';
  document.getElementById('tabbar').style.display = 'none';
  document.getElementById('hd-title').textContent = '飞洋OTMS · 登录';
}
function doLogin(){
  var u = document.getElementById('lg-u').value.trim();
  var p = document.getElementById('lg-p').value;
  if (!u || !p) { toast('请输入账号密码'); return; }
  api('/api/login', {method:'POST', body:{username:u, password:p}}).then(function(d){
    TOKEN = d.token; localStorage.setItem('feiyang_m_token', TOKEN);
    document.getElementById('tabbar').style.display = '';
    toast('登录成功'); render('dash');
  }).catch(function(e){ toast('登录失败：'+(e.message||e)); });
}
function logout(){
  TOKEN=''; localStorage.removeItem('feiyang_m_token'); showLogin();
}

/* ---------- 启动 ---------- */
if ('serviceWorker' in navigator) { navigator.serviceWorker.register('sw.js').catch(function(){}); }
if (!TOKEN) showLogin(); else render('dash');
