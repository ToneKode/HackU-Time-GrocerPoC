import contract from '../../contract.json'

const { hash_fields_in_order, hash_join, genesis_prev_hash } = contract.audit

export async function sha256Hex(text) {
  const bytes = new TextEncoder().encode(text)
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('')
}

// "index|ts|event|status|reason|prev_hash"
export function hashInput(entry) {
  return hash_fields_in_order.map((field) => String(entry[field])).join(hash_join)
}

// One boolean per entry: its hash is correct and it points at the entry before it.
export async function verifyChain(entries) {
  const results = []
  let prev = genesis_prev_hash
  for (const entry of entries) {
    const hashOk = (await sha256Hex(hashInput(entry))) === entry.hash
    results.push(hashOk && entry.prev_hash === prev)
    prev = entry.hash
  }
  return results
}

export { genesis_prev_hash }
