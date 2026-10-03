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
