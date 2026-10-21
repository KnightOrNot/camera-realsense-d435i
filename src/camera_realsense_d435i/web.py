"""Browser UI served by the same loopback API as the CLI."""

PAGE = """<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>D435i 远程相机</title>
<style>
body{margin:0;background:#10151d;color:#e9eef6;font:16px system-ui,sans-serif}
main{max-width:1400px;margin:auto;padding:28px}header{display:flex;align-items:center;gap:18px;flex-wrap:wrap}
h1{font-size:26px;margin:0}button,a{background:#28374a;color:white;border:1px solid #456080;border-radius:7px;padding:10px 18px;text-decoration:none;cursor:pointer}
.primary{background:#197d78}.views{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin:24px 0}
figure{margin:0;background:#19222e;border-radius:10px;padding:14px}img{width:100%;min-height:200px;object-fit:contain;background:#090d13}
figcaption{padding:10px 0;color:#b9c9db}#state{padding:10px;color:#9edcd3}pre{white-space:pre-wrap;word-break:break-word;color:#b9c9db}
.note{color:#b9c9db;font-size:14px}@media(max-width:800px){.views{grid-template-columns:1fr}}
</style><main><header><h1>RealSense D435i</h1><span id="state">连接中…</span>
<button class="primary" id="start">开始采集</button><button id="stop">停止采集</button>
<a href="/api/snapshot" download="d435i-snapshot.zip">保存 RGB-D 截图</a></header>
<p id="message" role="alert"></p><section class="views">
<figure><img id="color" alt="RGB 实时画面"><figcaption>RGB 彩色画面</figcaption></figure>
<figure><img id="depth" alt="深度实时画面"><figcaption>深度可视化</figcaption></figure></section>
<p class="note">深度预览使用伪彩色；截图包含原始 16-bit 深度 PNG、深度尺度及标定信息。
深度保持相机原生视角，未对齐到 RGB。停止后释放设备，画面不会继续显示旧帧。</p>
<details open><summary>设备与采集信息</summary><pre id="info"></pre></details></main>
<script>
let session=''; const $=id=>document.getElementById(id);
async function request(path,body){const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); const j=await r.json(); if(!r.ok)throw Error(j.error||r.statusText); return j;}
async function refresh(){try{const s=await request('/api/status');
$('state').textContent=s.state==='streaming'?'正在采集':'状态：'+s.state;
$('info').textContent=JSON.stringify({configuration:s.configuration,observed_fps:s.observed_fps,frame_age_s:s.frame_age_s,...s.metadata},null,2);
$('message').textContent=s.error||'';
if(s.state==='streaming'){if(session!==s.session){session=s.session;for(const n of ['color','depth'])$(n).src='/stream/'+n+'.mjpg?session='+session;}}
else{session='';for(const n of ['color','depth'])$(n).removeAttribute('src');}
}catch(e){$('state').textContent='连接断开';$('message').textContent=e.message;session='';for(const n of ['color','depth'])$(n).removeAttribute('src');}}
$('start').onclick=async()=>{try{await request('/api/start',{});await refresh();}catch(e){$('message').textContent=e.message;}};
$('stop').onclick=async()=>{try{await request('/api/stop',{});await refresh();}catch(e){$('message').textContent=e.message;}};
refresh();setInterval(refresh,1000);
</script></html>"""
