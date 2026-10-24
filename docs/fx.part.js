(function(){var host=FX.$('.hero-bg');if(!host)return;var cv=FX.layer(host);
var N=[['cron','⏱',.07,.09],['http','⇄',.16,.28],['parse','{ }',.05,.46],['if','◇',.14,.62],['ai','✦',.9,.1],['git','⑂',.83,.3],['notify','✉',.93,.5],['retry','↻',.84,.66],['state','▤',.5,.93]];
var E=[[0,1],[1,2],[2,3],[4,5],[5,6],[6,7],[3,8],[7,8],[1,3],[5,7]];
var nodes=[],pulses=[],drag=-1,gx=0,gy=0,hov=-1,W=0,H=0,spawn=0;
function col(){var s=getComputedStyle(document.documentElement);return{a:s.getPropertyValue('--accent').trim(),b:s.getPropertyValue('--accent2').trim(),t:s.getPropertyValue('--text').trim(),c:s.getPropertyValue('--card').trim(),l:FX.theme()}}
function init(w,h){W=w;H=h;var hh=Math.min(h,1000);nodes=N.map(function(n){return{l:n[0],i:n[1],x:n[2]*w,y:n[3]*hh*.9+40,vx:0,vy:0,hx:n[2]*w,hy:n[3]*hh*.9+40,s:w<600?.8:1}})}
function bez(a,b,t){var dx=(b.x-a.x)*.5,x0=a.x,y0=a.y,x1=a.x+dx,y1=a.y,x2=b.x-dx,y2=b.y,x3=b.x,y3=b.y,u=1-t;return[u*u*u*x0+3*u*u*t*x1+3*u*t*t*x2+t*t*t*x3,u*u*u*y0+3*u*u*t*y1+3*u*t*t*y2+t*t*t*y3]}
var lp=FX.loop(cv,function(c,w,h,t,dt,m){if(!nodes.length||W!==w)init(w,h);var C=col();c.clearRect(0,0,w,h);var nw=w<600?74:104,nh=w<600?30:38;
 nodes.forEach(function(n,i){if(i!==drag){n.vx+=(n.hx-n.x)*6*dt;n.vy+=(n.hy-n.y)*6*dt;n.vx*=.86;n.vy*=.86;n.x+=n.vx*dt*10;n.y+=n.vy*dt*10+Math.sin(t*.7+i)*.08}});
 hov=-1;if(m.in)nodes.forEach(function(n,i){if(Math.abs(m.x-n.x)<nw/2&&Math.abs(m.y-n.y)<nh/2)hov=i});
 var al=w<600?.5:.9;c.globalAlpha=al;c.lineWidth=2;
 E.forEach(function(e){var a=nodes[e[0]],b=nodes[e[1]];c.strokeStyle=C.a;c.globalAlpha=al*.35;c.beginPath();c.moveTo(a.x,a.y);var dx=(b.x-a.x)*.5;c.bezierCurveTo(a.x+dx,a.y,b.x-dx,b.y,b.x,b.y);c.stroke()});
 spawn-=dt;if(spawn<=0){spawn=.5;pulses.push({e:E[(Math.random()*E.length)|0],p:0,v:FX.rnd(.25,.5)})}
 for(var i=pulses.length-1;i>=0;i--){var p=pulses[i];p.p+=p.v*dt;if(p.p>=1){pulses.splice(i,1);continue}var q=bez(nodes[p.e[0]],nodes[p.e[1]],p.p);c.globalAlpha=al;c.fillStyle=C.b;c.shadowColor=C.b;c.shadowBlur=12;c.beginPath();c.arc(q[0],q[1],4,0,6.3);c.fill();c.shadowBlur=0}
 nodes.forEach(function(n,i){var on=i===hov||i===drag,x=n.x-nw/2,y=n.y-nh/2;c.globalAlpha=on?1:al*.85;c.fillStyle=C.c;c.strokeStyle=on?C.b:C.a;c.lineWidth=on?2.5:1.5;c.beginPath();c.roundRect?c.roundRect(x,y,nw,nh,10):c.rect(x,y,nw,nh);c.fill();c.stroke();
  c.fillStyle=C.a;c.beginPath();c.arc(x,n.y,4,0,6.3);c.arc(x+nw,n.y,4,0,6.3);c.fill();
  c.fillStyle=C.t;c.font='600 '+(w<600?11:13)+'px Sora,Vazirmatn,sans-serif';c.textBaseline='middle';c.textAlign='left';c.fillText(n.i+'  '+n.l,x+12,n.y+1)});
 c.globalAlpha=1;cv.style.cursor=hov>=0?'grab':'default';
},{still:3,dpr:1.5,resize:function(){nodes=[]}});
cv.style.pointerEvents='none';
/* hero text sits above the canvas; drive drag from the host instead, only when pressing on empty space */
host.addEventListener('pointerdown',function(e){if(e.target.closest('a,button,code,.install,.shot,h1,p,.pill'))return;var r=cv.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;nodes.forEach(function(n,i){if(Math.abs(x-n.x)<60&&Math.abs(y-n.y)<24){drag=i;gx=x-n.x;gy=y-n.y}});if(drag>=0){host.setPointerCapture&&host.setPointerCapture(e.pointerId)}});
host.addEventListener('pointermove',function(e){if(drag<0)return;var r=cv.getBoundingClientRect();nodes[drag].x=e.clientX-r.left-gx;nodes[drag].y=e.clientY-r.top-gy});
['pointerup','pointercancel'].forEach(function(n){host.addEventListener(n,function(){drag=-1})});
FX.reveal('.card,.step,.ex>*');
})();
