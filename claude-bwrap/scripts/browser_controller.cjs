const {spawn} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const crypto = require('node:crypto');

const TIMEZONE = 'UTC';
const CONTROLLER_REVISION = crypto.createHash('sha256').update(fs.readFileSync(__filename)).digest('hex');
const TARGET_FILTER = ['page', 'iframe', 'worker', 'shared_worker', 'service_worker']
  .map(type => ({type})).concat([{exclude: true}]);
const AUTO_ATTACH = {autoAttach: true, waitForDebuggerOnStart: true, flatten: true, filter: TARGET_FILTER};

function launchChrome({profile, port, headless = false, log = () => {}}) {
  const chrome = path.join(process.env.ProgramFiles, 'Google', 'Chrome', 'Application', 'chrome.exe');
  const args = [
    `--user-data-dir=${profile}`, `--proxy-server=http://127.0.0.1:${port}`,
    '--proxy-bypass-list=<-loopback>',
    '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1',
    '--remote-debugging-pipe', '--no-startup-window', '--lang=en-US', '--disable-quic',
    '--force-webrtc-ip-handling-policy=disable_non_proxied_udp', '--disable-extensions',
    '--disable-sync', '--no-first-run', '--no-default-browser-check',
  ];
  if (headless) args.push('--headless=new');
  const child = spawn(chrome, args, {stdio: ['ignore', 'ignore', 'ignore', 'pipe', 'pipe'], windowsHide: true});
  let serial = 0, input = Buffer.alloc(0), shuttingDown = false, fault;
  const pending = new Map(), targets = new Map(), sessions = new Map(), pages = new Set();

  function send(method, params = {}, sessionId) {
    return new Promise((resolve, reject) => {
      if (fault || child.exitCode !== null) return reject(fault || new Error('Browser exited'));
      const id = ++serial;
      const timeout = setTimeout(() => {
        pending.delete(id);
        reject(Object.assign(new Error(`Protocol timeout: ${method}`), {method, code: 'timeout'}));
      }, 8000);
      pending.set(id, {resolve, reject, timeout, method});
      child.stdio[3].write(JSON.stringify({id, method, params, ...(sessionId ? {sessionId} : {})}) + '\0');
    });
  }
  async function close() {
    if (shuttingDown) return;
    shuttingDown = true;
    try { await send('Browser.close'); } catch {}
    if (child.exitCode === null) {
      await Promise.race([new Promise(r => child.once('exit', r)), new Promise(r => setTimeout(r, 2000))]);
      if (child.exitCode === null) child.kill();
    }
  }
  async function configure({sessionId, targetInfo}) {
    // Chrome can attach the same shared worker through more than one parent.
    // One owner sets its timezone; the duplicate must not keep that worker paused.
    if (targets.has(targetInfo.targetId)) {
      try {
        await send('Runtime.runIfWaitingForDebugger', {}, sessionId);
        await send('Target.detachFromTarget', {sessionId});
      } catch (e) {
        if (!/Session with given id not found|No session with given id|Target closed|No target with given id/i.test(e.message)) throw e;
      }
      return;
    }
    const target = {sessionId, type: targetInfo.type};
    targets.set(targetInfo.targetId, target);
    sessions.set(sessionId, targetInfo.targetId);
    target.ready = (async () => {
      // A noopener popup may defer renderer replies until its resume command arrives.
      // Queue timezone and child interception before resume, then await all replies.
      await Promise.all([
        send('Emulation.setTimezoneOverride', {timezoneId: TIMEZONE}, sessionId),
        send('Target.setAutoAttach', AUTO_ATTACH, sessionId),
        send('Runtime.runIfWaitingForDebugger', {}, sessionId),
      ]);
      log('target-ready', {type: target.type});
      return sessionId;
    })();
    try { await target.ready; }
    catch (e) {
      // A tab or short-lived worker may disappear while its command is in flight.
      if (!sessions.has(sessionId) || shuttingDown) return;
      log('timezone-setup-failed', {type: target.type, method: e.method || 'initialize', code: e.code || 'protocol'});
      await close();
      fault = e;
    }
  }
  child.stdio[4].on('data', chunk => {
    try {
      input = Buffer.concat([input, chunk]);
      for (let end; (end = input.indexOf(0)) !== -1;) {
      const message = JSON.parse(input.subarray(0, end).toString());
      input = input.subarray(end + 1);
      if (message.id && pending.has(message.id)) {
        const p = pending.get(message.id); pending.delete(message.id); clearTimeout(p.timeout);
        if (message.error) {
          p.reject(Object.assign(new Error(`${message.error.code}: ${message.error.message}`), {method: p.method, code: message.error.code}));
        } else p.resolve(message.result);
      } else if (message.method === 'Target.attachedToTarget') {
        configure(message.params).catch(async e => {
          log('attach-failed', {type: message.params.targetInfo.type, code: /^-?\d+/.exec(e.message)?.[0] || 'protocol'});
          if (!shuttingDown) await close();
        });
      } else if (message.method === 'Target.detachedFromTarget') {
        const id = sessions.get(message.params.sessionId);
        if (id && targets.get(id)?.sessionId === message.params.sessionId) targets.delete(id);
        sessions.delete(message.params.sessionId);
      } else if (message.method === 'Target.targetCreated') {
        if (message.params.targetInfo.type === 'page') pages.add(message.params.targetInfo.targetId);
      } else if (message.method === 'Target.targetDestroyed') {
        // --no-startup-window otherwise keeps Chrome alive after its last window closes.
        if (pages.delete(message.params.targetId) && !pages.size && !shuttingDown) {
          log('last-page-closed');
          close().catch(() => child.kill());
        }
      }
      }
    } catch {
      log('protocol-parse-failed');
      close().catch(() => child.kill());
    }
  });
  const ended = error => {
    fault = error instanceof Error ? error : new Error('Browser exited');
    for (const p of pending.values()) { clearTimeout(p.timeout); p.reject(fault); }
    pending.clear();
  };
  child.on('error', ended);
  child.on('exit', ended);
  child.stdio[3].on('error', ended);
  child.stdio[4].on('error', ended);
  const started = (async () => {
    const version = (await send('Browser.getVersion')).product;
    await send('Target.setDiscoverTargets', {discover: true, filter: [{type: 'page'}, {exclude: true}]});
    await send('Target.setAutoAttach', AUTO_ATTACH);
    log('browser-ready', {version, timezone: TIMEZONE, revision: CONTROLLER_REVISION});
    return version;
  })();
  async function createPage(url) {
    await started;
    const {targetId} = await send('Target.createTarget', {url: 'about:blank'});
    const deadline = Date.now() + 10000;
    while (!targets.has(targetId)) {
      if (fault) throw fault;
      if (Date.now() >= deadline) throw new Error('Page did not attach');
      await new Promise(r => setTimeout(r, 25));
    }
    const sessionId = await targets.get(targetId).ready;
    const check = await send('Runtime.evaluate', {
      expression: '({timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,locale:Intl.DateTimeFormat().resolvedOptions().locale})',
      returnByValue: true,
    }, sessionId);
    const actual = check.result.value;
    if (actual?.timezone !== TIMEZONE || actual.locale !== 'en-US') {
      await send('Target.closeTarget', {targetId});
      throw new Error('Dedicated browser environment verification failed');
    }
    await send('Page.navigate', {url}, sessionId);
    return {targetId, sessionId};
  }
  return {child, started, send, createPage, close, targets};
}

function validUrl(value) {
  if (typeof value !== 'string' || value.length > 16384 || /[\x00-\x20]/.test(value)) return false;
  try { const u = new URL(value); return u.protocol === 'https:' && !u.username && !u.password; }
  catch { return false; }
}
function requestExisting(state, url) {
  return new Promise((resolve, reject) => {
    const socket = net.connect(state.pipe);
    let response = '';
    socket.setTimeout(20000, () => socket.destroy(new Error('Existing browser did not respond')));
    socket.once('connect', () => socket.write(JSON.stringify({token: state.token, url}) + '\n'));
    socket.on('data', chunk => {
      response += chunk;
      if (response.includes('\n')) {
        socket.end();
        try { const result = JSON.parse(response.split('\n')[0]); result.ok ? resolve(result) : reject(new Error('Existing browser refused request')); }
        catch (e) { reject(e); }
      }
    });
    socket.on('error', reject);
  });
}
async function requestRunning(stateFile, url, port) {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    let state;
    try { state = JSON.parse(fs.readFileSync(stateFile, 'utf8')); }
    catch (e) {
      if (e.code !== 'ENOENT' && !(e instanceof SyntaxError)) throw e;
      await new Promise(r => setTimeout(r, 100));
      continue;
    }
    if (state.revision !== CONTROLLER_REVISION || state.port !== port) throw new Error('Close the old dedicated browser and retry');
    try { return await requestExisting(state, url); }
    catch (e) { if (!['ENOENT', 'ECONNREFUSED'].includes(e.code)) throw e; }
    await new Promise(r => setTimeout(r, 100));
  }
  throw new Error('Browser controller did not become ready');
}
function prepareProfile(profile) {
  for (const [file, apply] of [
    ['Local State', data => { data.intl = {...data.intl, app_locale: 'en-US'}; }],
    ['Default/Preferences', data => {
      data.intl = {...data.intl, accept_languages: 'en-US,en', selected_languages: 'en-US,en'};
      data.webrtc = {...data.webrtc, ip_handling_policy: 'disable_non_proxied_udp'};
      data.profile ||= {};
      data.profile.default_content_setting_values = {...data.profile.default_content_setting_values, geolocation: 2};
    }],
  ]) {
    const filename = path.join(profile, file);
    const data = fs.existsSync(filename) ? JSON.parse(fs.readFileSync(filename, 'utf8')) : {};
    apply(data);
    fs.mkdirSync(path.dirname(filename), {recursive: true});
    const temp = filename + '.claude-guard.tmp';
    fs.writeFileSync(temp, JSON.stringify(data)); fs.renameSync(temp, filename);
  }
}
async function main() {
  const port = Number(process.env.WSL_AGENT_VERIFIED_PORT);
  if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('A verified local proxy port is required');
  const directory = path.join(process.env.LOCALAPPDATA, 'WslAgentPrivacyBrowser');
  fs.mkdirSync(directory, {recursive: true});
  const stateFile = path.join(directory, 'browser-controller.json');
  if (!process.argv.includes('--serve')) {
    let raw = '';
    for await (const part of process.stdin) {
      raw += part;
      if (raw.length > 20000) throw new Error('Request too large');
    }
    const request = JSON.parse(raw);
    if (!validUrl(request.url) || request.port !== port) throw new Error('Invalid browser request');
    const result = await requestRunning(stateFile, request.url, port);
    process.stdout.write(JSON.stringify(result) + '\n');
    return;
  }
  let lock;
  try { lock = fs.openSync(stateFile, 'wx'); }
  catch (e) {
    if (e.code !== 'EEXIST') throw e;
    const rawState = fs.readFileSync(stateFile, 'utf8');
    const previous = JSON.parse(rawState);
    try { process.kill(previous.pid, 0); return; }
    catch (dead) { if (dead.code !== 'ESRCH') throw dead; }
    if (fs.readFileSync(stateFile, 'utf8') !== rawState) throw new Error('Controller state changed');
    fs.unlinkSync(stateFile);
    lock = fs.openSync(stateFile, 'wx');
  }
  const state = {pid: process.pid, port, revision: CONTROLLER_REVISION, pipe: `\\\\.\\pipe\\claude-browser-${crypto.randomBytes(12).toString('hex')}`, token: crypto.randomBytes(32).toString('hex')};
  fs.writeFileSync(lock, JSON.stringify(state)); fs.closeSync(lock);
  const cleanup = () => {
    try { if (JSON.parse(fs.readFileSync(stateFile, 'utf8')).pid === process.pid) fs.unlinkSync(stateFile); } catch {}
  };
  const log = (event, values = {}) => fs.appendFileSync(path.join(directory, 'browser-controller.log'), JSON.stringify({time: new Date().toISOString(), event, ...values}) + '\n');
  let browser, server;
  try {
    prepareProfile(path.join(directory, 'ChromeProfile'));
    browser = launchChrome({profile: path.join(directory, 'ChromeProfile'), port, log});
    await browser.started;
    server = net.createServer(socket => {
      let input = '';
      socket.setTimeout(20000, () => socket.destroy());
      socket.on('data', async part => {
        input += part;
        if (input.length > 20000) return socket.destroy();
        if (!input.includes('\n')) return;
        socket.removeAllListeners('data');
        try {
          const message = JSON.parse(input.split('\n')[0]);
          if (message.token !== state.token || !validUrl(message.url)) throw new Error('Invalid request');
          await browser.createPage(message.url);
          socket.end(JSON.stringify({ok: true, reused: true}) + '\n');
        } catch { socket.end(JSON.stringify({ok: false}) + '\n'); }
      });
      socket.on('error', () => {});
    });
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(state.pipe, resolve); });
    browser.child.once('exit', () => { server.close(); cleanup(); });
    let stopping = false;
    const stop = async () => {
      if (stopping) return;
      stopping = true;
      server.close();
      await browser.close();
      cleanup();
    };
    process.once('SIGINT', stop);
    process.once('SIGTERM', stop);
    process.once('uncaughtException', () => { log('controller-failed'); stop().finally(() => process.exit(1)); });
    process.once('unhandledRejection', () => { log('controller-failed'); stop().finally(() => process.exit(1)); });
    process.once('exit', cleanup);
  } catch (e) {
    if (browser) await browser.close();
    if (server) server.close();
    cleanup(); log('launch-failed'); throw e;
  }
}

module.exports = {launchChrome, prepareProfile};
if (require.main === module) main().catch(() => {
  process.stdout.write(JSON.stringify({ok: false, error: 'Dedicated browser startup failed'}) + '\n');
  process.exitCode = 1;
});
