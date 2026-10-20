// Plain-language descriptions for audit log entries ("auth.login" -> "Logged in").

const LABELS: Record<string, string> = {
  "auth.login": "Logged in",
  "auth.login_failed": "Failed login attempt",
  "auth.password_changed": "Changed password",
  "auth.password_reset_requested": "Asked to reset password",
  "auth.password_reset": "Reset password",
  "admin.client_created": "Created client",
  "admin.client_updated": "Edited client",
  "admin.client_deleted": "Deleted client",
  "admin.website_created": "Added website",
  "admin.website_updated": "Edited website",
  "admin.website_deleted": "Deleted website",
  "admin.member_added": "Gave someone access",
  "admin.member_role_changed": "Changed a member's role",
  "admin.member_removed": "Removed someone's access",
  "admin.invite_link_created": "Created an invitation link",
  "admin.user_password_set": "Set a new password for a user",
  "admin.user_email_changed": "Changed a user's email",
  "admin.user_updated": "Edited a user",
  "admin.view_as_started": "Started viewing as a client",
  "admin.view_as_ended": "Stopped viewing as a client",
};

export function auditLabel(action: string): string {
  return LABELS[action] ?? action;
}

/** A short one-line summary of an entry's details (never contains secrets: the backend doesn't log any). */
export function auditSummary(details: Record<string, unknown> | null): string {
  if (!details) return "";
  return Object.entries(details)
    .map(([key, value]) => `${key.replace(/_/g, " ")}: ${Array.isArray(value) ? value.join(", ") : String(value)}`)
    .join(" · ");
}
