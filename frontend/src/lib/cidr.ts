// Trusted Hosts (FortiOS-style) — client-side validation and membership helpers.
//
// The backend is the source of truth for enforcement; these helpers only power
// the admin UI: validating what the operator types and warning about lock-out
// (does *my current IP* still fall inside the list I'm about to save?).

export type IpVersion = 4 | 6

export interface HostEntry {
  /** Original text, trimmed. */
  raw: string
  version: IpVersion
  /** Address portion (without the prefix). */
  address: string
  /** Prefix length; defaults to the full width (32 / 128) for a bare address. */
  prefix: number
  /** Canonical "address/prefix" form. */
  normalized: string
}

function parseIPv4(addr: string): number | null {
  const parts = addr.split('.')
  if (parts.length !== 4) return null
  let value = 0
  for (const part of parts) {
    if (!/^\d{1,3}$/.test(part)) return null
    const n = Number(part)
    if (n > 255) return null
    // Reject leading zeros like "01" to avoid ambiguity.
    if (part.length > 1 && part[0] === '0') return null
    value = value * 256 + n
  }
  // >>> 0 keeps it an unsigned 32-bit number.
  return value >>> 0
}

/** Expand an IPv6 address (including `::` compression) to a 128-bit BigInt. */
function parseIPv6(addr: string): bigint | null {
  // Reject obviously malformed input early.
  if (!/^[0-9a-fA-F:]+$/.test(addr)) return null
  const doubleColon = addr.split('::')
  if (doubleColon.length > 2) return null

  let head: string[] = []
  let tail: string[] = []
  if (doubleColon.length === 2) {
    head = doubleColon[0] ? doubleColon[0].split(':') : []
    tail = doubleColon[1] ? doubleColon[1].split(':') : []
    if (head.length + tail.length > 7) return null
  } else {
    head = addr.split(':')
    if (head.length !== 8) return null
  }

  const fill = 8 - head.length - tail.length
  const groups = [...head, ...Array(fill).fill('0'), ...tail]
  if (groups.length !== 8) return null

  let value = 0n
  for (const g of groups) {
    if (!/^[0-9a-fA-F]{1,4}$/.test(g)) return null
    value = (value << 16n) + BigInt(parseInt(g, 16))
  }
  return value
}

function detectVersion(addr: string): IpVersion | null {
  if (addr.includes(':')) return 6
  if (addr.includes('.')) return 4
  return null
}

/**
 * Validate and normalize a trusted-host entry: a bare IP or CIDR, IPv4 or IPv6.
 * Returns null when the value is not a valid host/CIDR.
 */
export function parseHostEntry(value: string): HostEntry | null {
  const raw = value.trim()
  if (!raw) return null

  const slash = raw.indexOf('/')
  const address = slash === -1 ? raw : raw.slice(0, slash)
  const prefixStr = slash === -1 ? null : raw.slice(slash + 1)

  const version = detectVersion(address)
  if (!version) return null

  const maxPrefix = version === 4 ? 32 : 128
  let prefix = maxPrefix
  if (prefixStr !== null) {
    if (!/^\d{1,3}$/.test(prefixStr)) return null
    prefix = Number(prefixStr)
    if (prefix > maxPrefix) return null
  }

  if (version === 4) {
    if (parseIPv4(address) === null) return null
  } else {
    if (parseIPv6(address) === null) return null
  }

  return { raw, version, address, prefix, normalized: `${address}/${prefix}` }
}

export function isValidHostEntry(value: string): boolean {
  return parseHostEntry(value) !== null
}

/**
 * Does `entry` (an IP or CIDR) cover `ip`? Used to warn an admin before they
 * save a trusted-host list that would exclude the address they're editing from.
 * Returns false if either side is unparseable or the versions differ.
 */
export function hostContainsIp(entry: string, ip: string): boolean {
  const host = parseHostEntry(entry)
  const target = parseHostEntry(ip)
  if (!host || !target) return false
  if (host.version !== target.version) return false

  if (host.version === 4) {
    const net = parseIPv4(host.address)!
    const addr = parseIPv4(target.address)!
    if (host.prefix === 0) return true
    const mask = host.prefix === 32 ? 0xffffffff : (0xffffffff << (32 - host.prefix)) >>> 0
    return (net & mask) === (addr & mask)
  }

  const net = parseIPv6(host.address)!
  const addr = parseIPv6(target.address)!
  if (host.prefix === 0) return true
  const mask = ((1n << 128n) - 1n) ^ ((1n << BigInt(128 - host.prefix)) - 1n)
  return (net & mask) === (addr & mask)
}

/** True when any entry in the list covers `ip` (i.e. access would be allowed). */
export function anyHostContainsIp(entries: string[], ip: string): boolean {
  return entries.some((e) => hostContainsIp(e, ip))
}
