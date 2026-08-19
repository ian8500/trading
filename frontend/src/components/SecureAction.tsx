import { useEffect, useId, useRef, useState } from "react";
import { ApiError, ApiNetworkError } from "../api/client";
import { useApi } from "../context/ApiContext";
import { Icon } from "./Icon";

interface SecureActionProps<TResponse> {
  label: string;
  title?: string;
  description: string;
  endpoint: string;
  method?: "POST" | "PUT" | "PATCH" | "DELETE";
  body?: Record<string, unknown>;
  variant?: "primary" | "secondary" | "danger";
  confirmationPhrase?: string;
  disabled?: boolean;
  onCompleted?: (response: TResponse) => void | Promise<void>;
}

export function SecureAction<TResponse = unknown>({
  label,
  title = label,
  description,
  endpoint,
  method = "POST",
  body,
  variant = "secondary",
  confirmationPhrase,
  disabled = false,
  onCompleted,
}: SecureActionProps<TResponse>) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const { request } = useApi();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [phrase, setPhrase] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<{ tone: "success" | "error"; message: string } | null>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const close = () => {
      setPassword("");
      setPhrase("");
      setResult(null);
    };
    dialog.addEventListener("close", close);
    return () => dialog.removeEventListener("close", close);
  }, []);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (confirmationPhrase && phrase !== confirmationPhrase) {
      setResult({ tone: "error", message: `Type “${confirmationPhrase}” exactly to continue.` });
      return;
    }
    setSubmitting(true);
    setResult(null);
    try {
      await request("/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      const response = await request<TResponse>(endpoint, {
        method,
        body: JSON.stringify(body ?? {}),
      });
      await onCompleted?.(response);
      setResult({ tone: "success", message: "Command accepted and recorded in the audit trail." });
    } catch (error) {
      const message = error instanceof ApiNetworkError
        ? "Backend unavailable. No control command was sent."
        : error instanceof ApiError && error.status === 401
          ? "Authentication failed. Check the local administrator credentials."
          : error instanceof Error
            ? error.message
            : "The command could not be completed.";
      setResult({ tone: "error", message });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <button
        type="button"
        className={`button button-${variant}`}
        disabled={disabled}
        onClick={() => dialogRef.current?.showModal()}
      >
        <Icon name={variant === "danger" ? "alert" : "lock"} size={16} />
        {label}
      </button>
      <dialog ref={dialogRef} className="secure-dialog" aria-labelledby={titleId}>
        <form onSubmit={submit} aria-busy={submitting}>
          <div className="dialog-header">
            <div className={`dialog-icon ${variant === "danger" ? "danger" : ""}`}><Icon name={variant === "danger" ? "alert" : "lock"} /></div>
            <div><p className="eyebrow">Authenticated control</p><h2 id={titleId}>{title}</h2></div>
            <button className="icon-button" type="button" aria-label="Close" onClick={() => dialogRef.current?.close()}><Icon name="close" /></button>
          </div>
          <p className="dialog-description">{description}</p>
          <div className="safety-callout"><strong>Fail-closed control</strong><span>The backend must authenticate, validate current risk state, and audit this action. Credentials are never stored in the browser.</span></div>
          <div className="form-grid">
            <label><span>Local administrator</span><input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required /></label>
            <label><span>Password</span><input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
            {confirmationPhrase && (
              <label className="span-2">
                <span>Type <strong>{confirmationPhrase}</strong> to confirm</span>
                <input value={phrase} onChange={(event) => setPhrase(event.target.value)} autoComplete="off" required />
              </label>
            )}
          </div>
          {result && (
            <div
              className={`dialog-result ${result.tone}`}
              role={result.tone === "error" ? "alert" : "status"}
              aria-live={result.tone === "error" ? "assertive" : "polite"}
              aria-atomic="true"
            >
              {result.message}
            </div>
          )}
          <div className="dialog-actions">
            <button type="button" className="button button-ghost" onClick={() => dialogRef.current?.close()}>Cancel</button>
            <button type="submit" className={`button button-${variant}`} disabled={submitting}>
              {submitting ? <span className="button-spinner" /> : <Icon name={variant === "danger" ? "alert" : "check"} size={16} />}
              {submitting ? "Authorising…" : label}
            </button>
          </div>
        </form>
      </dialog>
    </>
  );
}
