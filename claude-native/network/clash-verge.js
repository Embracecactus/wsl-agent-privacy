// Clash Verge Rev subscription extension. Select a concrete node from this profile.
const claudeNode = "CLAUDE_FIXED_NODE";
const claudePort = 17897;
const coverOtherClients = false;

function main(config) {
  if ((config.proxies || []).filter(proxy => proxy.name === claudeNode).length !== 1) {
    throw new Error("Select a concrete Claude node from the active profile's proxies.");
  }
  const listener = {name: "claude-private", type: "http", listen: "127.0.0.1", port: claudePort, proxy: claudeNode};
  const listeners = config.listeners || [];
  const matches = listeners.filter(item => item.name === listener.name || Number(item.port) === claudePort);
  if (matches.length) {
    const prior = matches[0];
    if (matches.length !== 1 || prior.name !== listener.name || Number(prior.port) !== claudePort || prior.type !== listener.type ||
        prior.listen !== listener.listen || prior.proxy !== claudeNode) {
      throw new Error("The Claude listener name or port is already assigned differently.");
    }
  } else {
    config.listeners = [...listeners, listener];
  }
  if (coverOtherClients) {
    if (/[,&#]/.test(claudeNode)) {
      throw new Error("Use a node name without a comma, ampersand or hash in rules and DNS fragments.");
    }
    const suffixes = ["anthropic.com", "claude.ai", "claude.com", "claudeusercontent.com"];
    const rules = suffixes.map(domain => "DOMAIN-SUFFIX," + domain + "," + claudeNode);
    config.rules = [...rules, ...(config.rules || []).filter(rule => !rules.includes(rule))];
    const dns = config.dns || {};
    const policy = {...dns["nameserver-policy"]};
    const resolver = "https://1.1.1.1/dns-query#" + encodeURIComponent(claudeNode) + "&ecs=0.0.0.0/0&ecs-override=true";
    for (const domain of suffixes) policy["+." + domain] = [resolver];
    config.dns = {...dns, "nameserver-policy": policy};
  }
  return config;
}
