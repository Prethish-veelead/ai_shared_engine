import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// Shared avatar-initials logic (used by Header.tsx and history/page.tsx).
// Handles both a display name ("Cynthia Carey" -> "CC") and an email/UPN
// used as a fallback ("cynthia@contoso.com" -> the domain is stripped first,
// so it becomes "CY" rather than splitting the domain in as a fake surname).
export function getInitials(label: string): string {
  if (!label) return "U";
  const local = label.includes("@") ? label.split("@")[0] : label;
  const parts = local.split(/[.\s_-]+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return local.slice(0, 2).toUpperCase();
}
