"use client";

// Q178：登录录入岛——粘贴 staff PAT 自检并写入 httpOnly cookie；已登录则展示当前
// 身份并提供登出。不做密码/注册/找回（V2）。
import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import styles from "../admin.module.css";
import { loginStaffAction, logoutStaffAction, type StaffMe } from "./actions";

export function LoginIsland({ initialMe }: { initialMe: StaffMe | null }) {
  const t = useTranslations("admin.staffAuth");
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [token, setToken] = useState("");
  const [me, setMe] = useState<StaffMe | null>(initialMe);
  const [error, setError] = useState<string | null>(null);

  function login() {
    setError(null);
    startTransition(async () => {
      const result = await loginStaffAction(token);
      if (result.ok) {
        setMe({
          staff_id: result.staff_id,
          staff_name: result.staff_name,
          roles: result.roles,
        });
        setToken("");
        router.push("/admin/token-cost");
        router.refresh();
      } else if (result.status === "empty") {
        setError(t("emptyToken"));
      } else if (result.status === "disabled") {
        setError(t("disabledHint"));
      } else if (result.status === 401) {
        setError(t("invalidHint"));
      } else {
        setError(t("invalidHint"));
      }
    });
  }

  function logout() {
    startTransition(async () => {
      await logoutStaffAction();
      setMe(null);
      router.refresh();
    });
  }

  if (me) {
    return (
      <section className={styles.section} data-testid="staff-current">
        <p className={styles.intro}>
          {t("identityLabel")}：<strong>{me.staff_name}</strong>（
          <code>{me.staff_id}</code>）
        </p>
        <p className={styles.metaLine}>
          {me.roles.map((role) => (
            <code key={role}>{role} </code>
          ))}
        </p>
        <div className={styles.provisionForm}>
          <button
            type="button"
            className={styles.secondaryButton}
            disabled={pending}
            onClick={logout}
          >
            {t("logout")}
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className={styles.section} data-testid="staff-login">
      <div className={styles.provisionForm}>
        <textarea
          className={styles.jsonArea}
          aria-label={t("tokenLabel")}
          placeholder={t("tokenPlaceholder")}
          value={token}
          rows={4}
          onChange={(event) => setToken(event.target.value)}
        />
      </div>
      <div className={styles.provisionForm}>
        <button
          type="button"
          className={styles.primaryButton}
          disabled={pending || token.trim().length === 0}
          onClick={login}
        >
          {t("submit")}
        </button>
      </div>
      {error && (
        <p className={styles.msgErr} role="status">
          {error}
        </p>
      )}
    </section>
  );
}
