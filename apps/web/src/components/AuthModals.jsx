import { useEffect, useState } from "react";
import { api } from "../api.js";
import Modal from "./Modal.jsx";

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.9 29.3 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3 0 5.8 1.1 7.9 3l5.7-5.7C34.2 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.5-.4-3.5z" />
      <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 16.1 19 13.2 24 13.2c3 0 5.8 1.1 7.9 3l5.7-5.7C34.2 6.1 29.3 4 24 4 16.3 4 9.6 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.3 26.7 36 24 36c-5.3 0-9.7-3.1-11.3-7.5l-6.5 5C9.5 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.3-2.2 4.2-4.1 5.6l.1.1 6.2 5.2C39.2 37.3 44 32 44 24c0-1.3-.1-2.5-.4-3.5z" />
    </svg>
  );
}

function PasswordField({ name, placeholder, minLength, autoComplete, value, onChange }) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="nb-auth-password">
      <input
        className="nb-auth-input"
        name={name}
        type={visible ? "text" : "password"}
        placeholder={placeholder}
        required
        minLength={minLength}
        autoComplete={autoComplete}
        {...(value !== undefined ? { value, onChange } : {})}
      />
      <button type="button" className="nb-auth-eye" onClick={() => setVisible((v) => !v)} tabIndex={-1}>
        {visible ? "Скрыть" : "Показать"}
      </button>
    </div>
  );
}

function GoogleButton({ label }) {
  return (
    <button type="button" className="nb-auth-google" onClick={() => { window.location.href = api.googleStartUrl(); }}>
      <GoogleIcon />
      <span>{label}</span>
    </button>
  );
}

/** mode: signin | signup | forgot | reset | verify_sent | complete_profile | totp */
export default function AuthModals({
  showLogin,
  showRegister,
  showTotpComplete,
  showCompleteProfile,
  showForgot,
  showReset,
  resetToken,
  onCloseLogin,
  onCloseRegister,
  onCloseTotpComplete,
  onCloseCompleteProfile,
  onCloseForgot,
  onCloseReset,
  onOpenRegister,
  onOpenLogin,
  onOpenForgot,
  onLogin,
  onRegister,
  onTotpComplete,
  onForgot,
  onReset,
  onCompleteProfile,
  onResendVerify,
  googleEnabled,
  passwordRegister = false,
  mailEnabled = false,
  trustedDeviceDays = 30,
  profileDraft,
}) {
  const [remember, setRemember] = useState(true);
  const [emailMode, setEmailMode] = useState(false);
  const [profileName, setProfileName] = useState("");
  const [resetPassword, setResetPassword] = useState("");

  const openAuth = showLogin || showRegister;
  const isRegister = showRegister;

  useEffect(() => {
    if (showLogin || showTotpComplete) setRemember(true);
    if (showLogin || showRegister) setEmailMode(false);
  }, [showLogin, showRegister, showTotpComplete]);

  useEffect(() => {
    if (showCompleteProfile && profileDraft?.suggested_username) {
      setProfileName(profileDraft.suggested_username);
    }
  }, [showCompleteProfile, profileDraft]);

  function closeAuth() {
    if (isRegister) onCloseRegister();
    else onCloseLogin();
  }

  return (
    <>
      {openAuth && (
        <Modal title="" onClose={closeAuth}>
          <div className="nb-auth">
            <div className="nb-auth-brand">Nano Banana</div>
            <h2 className="nb-auth-title">{isRegister ? "Создать аккаунт" : "С возвращением"}</h2>
            <p className="nb-auth-sub">
              {isRegister
                ? "Google или email + пароль. После регистрации на email придёт ссылка подтверждения."
                : "Войдите через Google или email. Новый Google-аккаунт создаётся автоматически."}
            </p>

            {googleEnabled && <GoogleButton label="Продолжить с Google" />}

            {googleEnabled && (
              <div className="nb-auth-divider">
                <span>или</span>
              </div>
            )}

            {!emailMode ? (
              <button type="button" className="nb-auth-secondary" onClick={() => setEmailMode(true)}>
                Продолжить с email
              </button>
            ) : isRegister ? (
              passwordRegister ? (
                <form
                  className="nb-auth-form"
                  onSubmit={(e) => {
                    e.preventDefault();
                    onRegister(e);
                  }}
                >
                  <label className="nb-auth-label">Имя</label>
                  <input
                    className="nb-auth-input"
                    name="username"
                    placeholder="Как к вам обращаться"
                    required
                    minLength={3}
                    maxLength={32}
                    autoComplete="username"
                    autoCapitalize="none"
                    spellCheck={false}
                  />
                  <label className="nb-auth-label">Email</label>
                  <input className="nb-auth-input" name="email" type="email" placeholder="you@yandex.ru" required autoComplete="email" />
                  <label className="nb-auth-label">Пароль</label>
                  <PasswordField name="password" placeholder="От 10 символов" minLength={10} autoComplete="new-password" />
                  <button type="submit" className="nb-auth-primary">
                    Создать аккаунт
                  </button>
                  {mailEnabled && (
                    <p className="nb-auth-note">
                      На почту придёт ссылка подтверждения. Генерации откроет администратор после проверки.
                    </p>
                  )}
                </form>
              ) : (
                <div className="nb-auth-note">
                  Регистрация по email временно недоступна. Используйте Google или попросите доступ у администратора.
                </div>
              )
            ) : (
              <form
                className="nb-auth-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  const form = new FormData(e.target);
                  onLogin(form, remember);
                }}
              >
                <label className="nb-auth-label">Email или имя</label>
                <input
                  className="nb-auth-input"
                  name="username"
                  type="text"
                  placeholder="you@email.com"
                  required
                  autoComplete="username"
                  autoCapitalize="none"
                  spellCheck={false}
                />
                <label className="nb-auth-label">Пароль</label>
                <PasswordField name="password" placeholder="Пароль" autoComplete="current-password" />
                <label className="nb-auth-label">Код 2FA (если включён)</label>
                <input className="nb-auth-input" name="totp" inputMode="numeric" autoComplete="one-time-code" maxLength={6} placeholder="6 цифр — можно пусто" />
                <label className="nb-auth-check">
                  <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
                  Запомнить устройство {trustedDeviceDays} дн.
                </label>
                <button type="submit" className="nb-auth-primary">
                  Войти
                </button>
                {mailEnabled && (
                  <button type="button" className="nb-auth-link nb-auth-forgot" onClick={onOpenForgot}>
                    Забыли пароль?
                  </button>
                )}
              </form>
            )}

            <p className="nb-auth-switch">
              {isRegister ? (
                <>
                  Уже есть аккаунт?{" "}
                  <button type="button" className="nb-auth-link" onClick={onOpenLogin}>
                    Войти
                  </button>
                </>
              ) : (
                <>
                  Нет аккаунта?{" "}
                  <button type="button" className="nb-auth-link" onClick={onOpenRegister}>
                    Зарегистрироваться
                  </button>
                </>
              )}
            </p>
          </div>
        </Modal>
      )}

      {showForgot && (
        <Modal title="Восстановление пароля" onClose={onCloseForgot}>
          <div className="nb-auth">
            <p className="nb-auth-sub">Укажите email — пришлём ссылку для нового пароля.</p>
            <form
              className="nb-auth-form"
              onSubmit={(e) => {
                e.preventDefault();
                const form = new FormData(e.target);
                onForgot(String(form.get("email") || ""));
              }}
            >
              <label className="nb-auth-label">Email</label>
              <input className="nb-auth-input" name="email" type="email" required autoComplete="email" />
              <button type="submit" className="nb-auth-primary">
                Отправить ссылку
              </button>
            </form>
            <p className="nb-auth-switch">
              <button type="button" className="nb-auth-link" onClick={onOpenLogin}>
                Назад ко входу
              </button>
            </p>
          </div>
        </Modal>
      )}

      {showReset && (
        <Modal title="Новый пароль" onClose={onCloseReset}>
          <div className="nb-auth">
            <p className="nb-auth-sub">Придумайте новый пароль (от 10 символов).</p>
            <form
              className="nb-auth-form"
              onSubmit={(e) => {
                e.preventDefault();
                onReset(resetToken, resetPassword);
              }}
            >
              <label className="nb-auth-label">Новый пароль</label>
              <PasswordField
                name="password"
                placeholder="От 10 символов"
                minLength={10}
                autoComplete="new-password"
                value={resetPassword}
                onChange={(e) => setResetPassword(e.target.value)}
              />
              <button type="submit" className="nb-auth-primary" disabled={!resetToken}>
                Сохранить и войти
              </button>
            </form>
          </div>
        </Modal>
      )}

      {showCompleteProfile && (
        <Modal title="Завершите регистрацию" onClose={onCloseCompleteProfile}>
          <div className="nb-auth">
            <p className="nb-auth-sub">Google подтвердил почту. Проверьте имя — его увидят в сервисе.</p>
            <form
              className="nb-auth-form"
              onSubmit={(e) => {
                e.preventDefault();
                onCompleteProfile(profileName.trim());
              }}
            >
              <label className="nb-auth-label">Email</label>
              <input className="nb-auth-input" value={profileDraft?.email || ""} disabled readOnly />
              <label className="nb-auth-label">Имя</label>
              <input
                className="nb-auth-input"
                value={profileName}
                onChange={(e) => setProfileName(e.target.value)}
                required
                minLength={3}
                maxLength={32}
                autoComplete="username"
                autoFocus
              />
              <button type="submit" className="nb-auth-primary">
                Продолжить
              </button>
            </form>
          </div>
        </Modal>
      )}

      {showTotpComplete && (
        <Modal title="Подтвердите вход" onClose={onCloseTotpComplete}>
          <div className="nb-auth">
            <p className="nb-auth-sub">Введите код из приложения-аутентификатора.</p>
            <form
              className="nb-auth-form"
              onSubmit={(e) => {
                e.preventDefault();
                const form = new FormData(e.target);
                onTotpComplete(form.get("code"), remember);
              }}
            >
              <input className="nb-auth-input" name="code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} placeholder="6 цифр" required autoFocus />
              <label className="nb-auth-check">
                <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
                Запомнить устройство на {trustedDeviceDays} дн.
              </label>
              <button type="submit" className="nb-auth-primary">
                Продолжить
              </button>
            </form>
          </div>
        </Modal>
      )}
    </>
  );
}
