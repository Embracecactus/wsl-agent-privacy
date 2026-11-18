// Host-only regression: deployed controller, temporary profile, local proxy.
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),http=require('node:http');
const controller = process.argv[2] ? path.resolve(process.argv[2])
  : path.join(__dirname, '..', 'wsl-agent-privacy', 'scripts', 'browser_controller.cjs');
if (!fs.existsSync(controller)) {
  process.stdout.write(JSON.stringify({error: 'dedicated browser controller is missing'}));
  process.exit(1);
}
const {launchChrome,prepareProfile}=require(controller),folder=fs.mkdtempSync(path.join(os.tmpdir(),'agent-browser-regression-'));
const initialTimezone=Intl.DateTimeFormat().resolvedOptions().timeZone,result={chrome:null,checks:{}};
const proxyMark = require('node:crypto').randomUUID();
const plainName = 'dedicated-plain-canary.test';
const tunnelName = 'dedicated-tls-canary.test';
const offlineName = 'dedicated-offline-canary.test';
let plainSeen = false, tunnelSeen = false;
let origin=0, directHits=0, browser; const originSockets=new Set(),proxySockets=new Set();
const snapshot = `({
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  locale: Intl.DateTimeFormat().resolvedOptions().locale,
  winterOffset: new Date(Date.UTC(2024, 0, 15, 12)).getTimezoneOffset(),
  summerOffset: new Date(Date.UTC(2024, 6, 15, 12)).getTimezoneOffset()
})`;
const server=http.createServer((q,r)=>{origin++; if (q.headers['x-regression-proxy'] !== proxyMark) directHits++; r.setHeader('content-type',q.url==='/w.js'?'application/javascript':'text/html');if(q.url==='/w.js')return r.end(`postMessage(${snapshot})`);if(q.url==='/frame')return r.end(`<script>parent.postMessage({frame:${snapshot}},'*')</script>`);r.end(`<script>window.p={page:${snapshot}};new Worker('/w.js').onmessage=e=>p.worker=e.data;onmessage=e=>{if(e.data.frame)p.frame=e.data.frame}</script><iframe src="http://localhost:${server.address().port}/frame"></iframe>`)});
server.on('connection',s=>{originSockets.add(s);s.on('close',()=>originSockets.delete(s))});
const proxy=http.createServer((q,r)=>{let u;try{u=new URL(q.url)}catch{return r.destroy()};if(!['127.0.0.1','localhost',plainName].includes(u.hostname)||Number(u.port)!==server.address().port){r.writeHead(403);return r.end()}if(u.hostname===plainName)plainSeen=true;const x=http.request({host:'127.0.0.1',port:server.address().port,path:u.pathname,headers:{...q.headers, 'x-regression-proxy': proxyMark}},z=>{r.writeHead(z.statusCode,z.headers);z.pipe(r)});x.on('error',()=>r.destroy());q.pipe(x)});
proxy.on('connection',s=>{proxySockets.add(s);s.on('close',()=>proxySockets.delete(s))});
proxy.on('connect', (req, socket) => {
  if (req.url === tunnelName + ':443') tunnelSeen = true;
  socket.end('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n');
});
const delay=n=>new Promise(r=>setTimeout(r,n));
async function closeServer(s,sockets){for(const x of sockets)x.destroy();await Promise.race([new Promise(r=>s.close(r)),delay(3000)]);}
async function stopProxy(){await closeServer(proxy,proxySockets)}
async function wait(fn){for(let n=0;n<240;n++){const x=await fn();if(x)return x;await delay(50)}throw Error('probe timeout')}
(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  await new Promise(r => proxy.listen(0, '127.0.0.1', r));
  const profile = path.join(folder, 'profile');
  prepareProfile(profile);
  browser = launchChrome({profile, port: proxy.address().port, headless: true});
  result.chrome = await browser.started;
  const {sessionId} = await browser.createPage(`http://127.0.0.1:${server.address().port}/`);
  const contexts = await wait(async () => {
    const x = await browser.send('Runtime.evaluate', {expression: 'window.p', returnByValue: true}, sessionId);
    const values = x.result.value;
    return values?.page && values.frame && values.worker && values;
  });
  for (const v of Object.values(contexts)) {
    if (v.timezone !== 'UTC' || v.locale !== 'en-US') throw Error('locale/timezone mismatch');
    if (v.winterOffset !== 0 || v.summerOffset !== 0) throw Error('seasonal timezone offset mismatch');
  }
  result.checks.timezone_and_locale = true;
  result.checks.seasonal_timezone_offsets = true;
  result.checks.used_proxy = origin > 0 && directHits === 0;
const rtc = await browser.send('Runtime.evaluate', {
  expression: `(async () => {
    const peer = new RTCPeerConnection({iceServers: []});
    const types = [];
    let timer;
    try {
      const done = new Promise((resolve, reject) => {
        peer.onicecandidate = event => event.candidate ? types.push(event.candidate.type) : resolve();
        timer = setTimeout(() => reject(Error('ICE timeout')), 6000);
      });
      peer.createDataChannel('check');
      await peer.setLocalDescription(await peer.createOffer());
      if (peer.iceGatheringState !== 'complete') await done;
      return types;
    } finally {
      clearTimeout(timer);
      peer.close();
    }
  })()`,
  awaitPromise: true,
  returnByValue: true,
}, sessionId);
result.checks.non_proxied_webrtc_udp = !rtc.exceptionDetails && Array.isArray(rtc.result?.value)
  && !rtc.result.value.includes('host');
const next = await browser.createPage('about:blank');
const go = url => browser.send('Page.navigate', {url}, next.sessionId);
const plain = await go(`http://${plainName}:${server.address().port}/`);
const encrypted = await go(`https://${tunnelName}/`);
result.checks.new_hostname_forwarded = !plain.errorText && plainSeen && directHits === 0;
result.checks.https_connect_carries_hostname = tunnelSeen && encrypted.errorText === 'net::ERR_TUNNEL_CONNECTION_FAILED';
await stopProxy();
const before = origin;
const failed = await go(`http://127.0.0.1:${server.address().port}/offline`);
const offline = await go(`https://${offlineName}/`);
result.checks.no_direct_fallback = failed.errorText === 'net::ERR_PROXY_CONNECTION_FAILED' && origin === before;
result.checks.offline_new_hostname_blocked = offline.errorText === 'net::ERR_PROXY_CONNECTION_FAILED';
result.checks.host_timezone_unchanged=initialTimezone===Intl.DateTimeFormat().resolvedOptions().timeZone;if(Object.values(result.checks).some(x=>x!==true))throw Error('browser regression failed')})().catch(e=>{result.error=e.message;process.exitCode=1}).finally(async()=>{try{if(browser)await browser.close()}catch{}try{await stopProxy()}catch{}try{await closeServer(server,originSockets)}catch{}try{fs.rmSync(folder,{recursive:true,force:true})}catch{}console.log(JSON.stringify(result))});
