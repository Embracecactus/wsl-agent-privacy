"""Read a rendered Mihomo profile locally and report only the coverage count."""
import argparse
from pathlib import Path
import sys
from urllib.parse import parse_qs, unquote, urlsplit

import yaml

SUFFIXES = {
    "claude": ("anthropic.com", "claude.ai", "claude.com", "claudeusercontent.com"),
    "codex": ("auth.openai.com", "chatgpt.com", "openai.com",
              "oaistatic.com", "oaiusercontent.com", "oaistatsig.com"),
}


def verify(profile, tool, node):
    policy = profile["dns"]["nameserver-policy"]
    for suffix in SUFFIXES[tool]:
        resolvers = policy.get("+." + suffix)
        if not isinstance(resolvers, list) or not resolvers:
            raise ValueError
        for resolver in resolvers:
            u = urlsplit(resolver)
            selected, _, options = u.fragment.partition("&")
            if (u.scheme != "https" or not u.hostname or u.username or u.password or u.path != "/dns-query"
                    or unquote(selected) != node
                    or parse_qs(options) != {"ecs": ["0.0.0.0/0"], "ecs-override": ["true"]}):
                raise ValueError
    return len(SUFFIXES[tool])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument("tool", choices=SUFFIXES)
    parser.add_argument("node", help="expected local fixed node")
    args = parser.parse_args()
    try:
        count = verify(yaml.safe_load(args.profile.read_text(encoding="utf-8-sig")), args.tool, args.node)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, yaml.YAMLError):
        sys.exit("DNS configuration unavailable or coverage mismatch")
    print(f"{args.tool}: {count} protected suffixes match")
