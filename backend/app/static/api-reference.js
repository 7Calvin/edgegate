
(function(){
  var q=document.getElementById('search');
  var ops=[].slice.call(document.querySelectorAll('.op'));
  var links=[].slice.call(document.querySelectorAll('.nav-link'));
  var sections=[].slice.call(document.querySelectorAll('.tag-section'));
  var navGroups=[].slice.call(document.querySelectorAll('.nav-group'));
  var noresult=document.getElementById('noresult');
  var monOnly=false;
  function apply(){
    var t=q.value.trim().toLowerCase();
    var any=false;
    ops.forEach(function(o){
      var hit=(!t||o.getAttribute('data-search').indexOf(t)>=0)&&(!monOnly||o.hasAttribute('data-mon'));
      o.style.display=hit?'':'none'; if(hit)any=true;
    });
    links.forEach(function(l){
      l.style.display=((!t||l.getAttribute('data-search').indexOf(t)>=0)&&(!monOnly||l.hasAttribute('data-mon')))?'':'none';
    });
    sections.forEach(function(s){
      var vis=s.querySelectorAll('.op:not([style*="none"])').length>0;
      s.style.display=vis?'':'none';
    });
    navGroups.forEach(function(g){
      var vis=g.querySelectorAll('.nav-link:not([style*="none"])').length>0;
      g.style.display=vis?'':'none';
    });
    noresult.style.display=any?'none':'';
  }
  q.addEventListener('input',apply);
  document.getElementById('tabs').addEventListener('click',function(e){
    var b=e.target.closest('.tab'); if(!b)return;
    monOnly=b.getAttribute('data-view')==='mon';
    [].slice.call(document.querySelectorAll('.tab')).forEach(function(x){x.classList.toggle('active',x===b);});
    apply();
  });
  // smooth scroll + keep hash
  document.getElementById('nav').addEventListener('click',function(e){
    var a=e.target.closest('a'); if(!a)return;
    e.preventDefault();
    var el=document.querySelector(a.getAttribute('href'));
    if(el)el.scrollIntoView({behavior:'smooth',block:'start'});
  });
})();
