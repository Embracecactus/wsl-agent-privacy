$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)

$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
if ($request.pipe -notmatch '^[A-Za-z0-9_.-]{1,128}$') { exit 2 }
if ($request.action -notin @('proxy', 'connections', 'listener')) { exit 2 }
if ($request.secret -and $request.secret -match '[\r\n]') { exit 2 }

function Invoke-Controller([string] $method, [string] $endpoint) {
    $pipe = [IO.Pipes.NamedPipeClientStream]::new('.', [string]$request.pipe,
        [IO.Pipes.PipeDirection]::InOut, [IO.Pipes.PipeOptions]::Asynchronous)
    try {
        $pipe.Connect(2500)
        $newline = [Environment]::NewLine
        $headers = $method + ' ' + $endpoint + ' HTTP/1.0' + $newline
        $headers += 'Host: localhost' + $newline + 'Connection: close' + $newline
        if ($request.secret) { $headers += 'Authorization: Bearer ' + $request.secret + $newline }
        $headers += $newline
        $bytes = [Text.Encoding]::ASCII.GetBytes($headers)
        $pipe.Write($bytes, 0, $bytes.Length)
        $pipe.Flush()
        $reader = [IO.StreamReader]::new($pipe)
        $pending = $reader.ReadToEndAsync()
        if (-not $pending.Wait(8000)) { throw 'timeout' }
        $raw = $pending.Result
        if ($raw.Length -gt 2097152) { throw 'response too large' }
        $separator = [Environment]::NewLine + [Environment]::NewLine
        $parts = $raw -split [regex]::Escape($separator), 2
        if ($parts.Count -ne 2 -or $parts[0] -notmatch '^HTTP/\S+ 200') { throw 'controller rejected' }
        return $parts[1] | ConvertFrom-Json
    } finally {
        $pipe.Dispose()
    }
}

try {
    if ($request.action -eq 'listener') {
        if ([int]$request.port -lt 1024 -or [int]$request.port -gt 65535) { exit 2 }
        if ($request.listener_owner -and [string]$request.listener_owner -notmatch '^[A-Za-z0-9_.-]{1,128}$') { exit 2 }
        $listeners = @(Get-NetTCPConnection -State Listen -LocalPort ([int]$request.port) -ErrorAction Stop)
        if ($listeners.Count -ne 1 -or $listeners[0].LocalAddress -ne '127.0.0.1') {
            @{ok=$false} | ConvertTo-Json -Compress
            exit 0
        }
        if ($request.listener_owner) {
            $owner = Get-Process -Id $listeners[0].OwningProcess -ErrorAction Stop
            if ($owner.ProcessName -ne [string]$request.listener_owner) {
                @{ok=$false} | ConvertTo-Json -Compress
                exit 0
            }
        }
        @{ok=$true} | ConvertTo-Json -Compress
        exit 0
    }
    if ($request.action -eq 'proxy') {
        if ([string]$request.node -match '[\x00-\x1f\x7f]' -or [string]$request.node.Length -gt 256) { exit 2 }
        $node = [Uri]::EscapeDataString([string]$request.node)
        $proxy = Invoke-Controller 'GET' ('/proxies/' + $node)
        @{type=$proxy.type} | ConvertTo-Json -Compress
        exit 0
    }
    if ([int]$request.source_port -lt 1024 -or [int]$request.source_port -gt 65535) { exit 2 }
    if ([string]$request.host -notin @('api.anthropic.com', 'chatgpt.com')) { exit 2 }
    $all = Invoke-Controller 'GET' '/connections'
    $matches = @($all.connections | Where-Object {
        [string]$_.metadata.sourcePort -eq [string]$request.source_port -and
        [string]$_.metadata.host -eq [string]$request.host
    } | ForEach-Object {
        $entry = @{chains=@($_.chains); specialProxy=$_.metadata.specialProxy; inboundPort=$_.metadata.inboundPort}
        foreach ($field in @('inbound', 'inboundName', 'inboundTag')) {
            if ($_.PSObject.Properties[$field]) {
                $entry[$field] = $_.PSObject.Properties[$field].Value
            } elseif ($_.metadata.PSObject.Properties[$field]) {
                $entry[$field] = $_.metadata.PSObject.Properties[$field].Value
            }
        }
        $entry
    })
    @{matches=$matches} | ConvertTo-Json -Compress -Depth 8
    exit 0
} catch {
    exit 1
}
