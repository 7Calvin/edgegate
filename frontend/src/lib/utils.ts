import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"
import { format, formatDistanceToNow, parseISO } from "date-fns"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatBytes(bytes: number | undefined | null, decimals = 2): string {
  if (bytes === undefined || bytes === null || isNaN(bytes)) return "0 Bytes"
  if (bytes === 0) return "0 Bytes"
  if (bytes < 0) return "0 Bytes"

  const k = 1024
  const dm = decimals < 0 ? 0 : decimals
  const sizes = ["Bytes", "KB", "MB", "GB", "TB", "PB"]

  const i = Math.floor(Math.log(bytes) / Math.log(k))
  if (i < 0 || i >= sizes.length) return "0 Bytes"

  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + " " + sizes[i]
}

export function formatDuration(seconds: number | undefined | null): string {
  if (seconds === undefined || seconds === null || isNaN(seconds) || seconds <= 0) return "0s"

  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const secs = Math.floor(seconds % 60)

  const parts = []
  if (days > 0) parts.push(`${days}d`)
  if (hours > 0) parts.push(`${hours}h`)
  if (minutes > 0) parts.push(`${minutes}m`)
  if (secs > 0 || parts.length === 0) parts.push(`${secs}s`)

  return parts.join(" ")
}

export function formatDate(date: string | Date, formatStr = "PPP"): string {
  if (!date) return "-"

  const dateObj = typeof date === "string" ? parseISO(date) : date
  return format(dateObj, formatStr)
}

export function formatDateRelative(date: string | Date): string {
  if (!date) return "-"

  const dateObj = typeof date === "string" ? parseISO(date) : date
  return formatDistanceToNow(dateObj, { addSuffix: true })
}

export function formatCertificateExpiry(expiryDate?: string | Date | null): {
  formatted: string
  text: string
  daysRemaining: number
  isExpiringSoon: boolean
  isExpired: boolean
} {
  if (!expiryDate) {
    return {
      formatted: "-",
      text: "No expiry date",
      daysRemaining: 0,
      isExpiringSoon: false,
      isExpired: true,
    }
  }

  const dateObj = typeof expiryDate === "string" ? parseISO(expiryDate) : expiryDate
  const now = new Date()
  const daysRemaining = Math.floor((dateObj.getTime() - now.getTime()) / (1000 * 60 * 60 * 24))

  let text = ""
  if (daysRemaining <= 0) {
    text = "Expired"
  } else if (daysRemaining <= 7) {
    text = `${daysRemaining} day${daysRemaining !== 1 ? 's' : ''} remaining`
  } else if (daysRemaining <= 30) {
    text = `${daysRemaining} days remaining`
  } else {
    text = format(dateObj, "PPP")
  }

  return {
    formatted: format(dateObj, "PPP"),
    text,
    daysRemaining,
    isExpiringSoon: daysRemaining <= 30 && daysRemaining > 0,
    isExpired: daysRemaining <= 0,
  }
}
