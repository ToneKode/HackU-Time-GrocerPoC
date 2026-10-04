import contract from '../../contract.json'

const { prefix, decimals } = contract.money

// 119.9 -> "HK$119.90"
export function money(amount) {
  if (amount == null) return '—'
  return prefix + Number(amount).toLocaleString('en-HK', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

// 600 -> "10:00", 59 -> "0:59"
export function clock(seconds) {
  const s = Math.max(0, Math.floor(seconds ?? 0))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

export function shortHash(hash) {
  return hash ? hash.slice(0, 10) + '…' : ''
}

export function reasonParts(text) {
  return String(text || '').split(/\n+/).map((part) => part.trim()).filter(Boolean)
}

export function lineReasons(line) {
  return [...new Set(reasonParts([line.product_reason || line.reason, line.merchant_reason].filter(Boolean).join('\n')))]
}

export function lineArithmetic(line) {
  const qty = Number(line.qty) || 0
  const total = Number(line.line_total)
  const unit = line.unit_price ?? (qty ? total / qty : null)
  return `${qty} × ${money(unit)} = ${money(line.line_total)}`
}

export function paidLines(lines) {
  return (lines || []).filter((line) => !line.is_gift)
}

// Separate gifts take precedence over duplicate inline representations.
export function giftLines(source) {
  const groups = source?.settlement?.merchants || source?.merchants || []
  const explicit = [source?.gifts, source?.settlement?.gifts].find((rows) => rows?.length)
  const grouped = groups.flatMap((group) => (group.gifts || []).map((gift) => ({ merchant: group.merchant, ...gift })))
  const direct = (source?.lines || []).filter((line) => line.is_gift)
  const inline = direct.length ? direct : groups.flatMap((group) => (group.lines || []).filter((line) => line.is_gift).map((gift) => ({ merchant: group.merchant, ...gift })))
  const rows = explicit || (grouped.length ? grouped : inline)
  const seen = new Set()
  return rows.filter((gift) => {
    const key = JSON.stringify([gift.merchant || '', gift.sku, gift.promotion_id || '', gift.qty])
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}
