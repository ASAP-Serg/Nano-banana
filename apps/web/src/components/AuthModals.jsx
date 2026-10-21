import { useEffect, useState } from "react";
import { api } from "../api.js";
import Modal from "./Modal.jsx";

function PasswordField({ name, placeholder, minLength }) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="input-group mb-3">
      <input
        className="form-control"
        name={name}
        type={visible ? "text" : "password"}
        placeholder={placeholder}
        required
        minLength={minLength}
      />
      <button type="button" className="btn btn-outline-secondary" onClick={() => setVisible((v) => !v)}>
        {visible ? "Скрыть" : "Показать"}
      </button>
    </div>
  );
}

function GoogleButton({ label = "Войти через Google" }) {
  return (
    <button
      type="button"
      className="btn btn-outline-dark w-100 mb-3"
      onClick={() => {
        window.location.href = api.googleStartUrl();
      }}
    >
      {label}
    </button>
  );
}

export default function AuthModals({
  showLogin,
  showRegister,
  showTotpComplete,
  onCloseLogin,
  onCloseRegister,
  onCloseTotpComplete,
  onOpenRegister,
  onLogin,
  onRegister,
  onTotpComplete,
  googleEnabled,
  trustedDeviceDays = 30,
}) {
  const [remember, setRemember] = useState(true);

  useEffect(() => {
    if (showLogin || showTotpComplete) setRemember(true);
  }, [showLogin, showTotpComplete]);

  return (
    <>
      {showLogin && (
        <Modal title="Вход" onClose={onCloseLogin}>
          {googleEnabled && <GoogleButton />}
          {googleEnabled && <p className="text-center text-muted small mb-3">или паролем</p>}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const form = new FormData(e.target);
              onLogin(form, remember);
            }}
          >
            <input className="form-control mb-2" name="username" placeholder="Имя или email" required autoComplete="username" />
            <PasswordField name="password" placeholder="Пароль" />
            <input
              className="form-control mb-1"
              name="totp"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              placeholder="Код 2FA (если включён)"
            />
            <div className="form-check mb-3">
              <input
                className="form-check-input"
                type="checkbox"
                id="rememberDeviceLogin"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
              />
              <label className="form-check-label" htmlFor="rememberDeviceLogin">
                Запомнить это устройство на {trustedDeviceDays} дн. (не спрашивать 2FA)
              </label>
            </div>
            <button className="btn btn-primary w-100">Войти</button>
            <button type="button" className="btn btn-link w-100" onClick={onOpenRegister}>
              Нет аккаунта? Регистрация
            </button>
          </form>
        </Modal>
      )}
      {showRegister && (
        <Modal title="Регистрация" onClose={onCloseRegister}>
          {googleEnabled && (
            <>
              <GoogleButton label="Создать аккаунт через Google" />
              <p className="text-center text-muted small mb-3">
                Рекомендуемый способ — Google. Регистрация паролем может быть отключена.
              </p>
            </>
          )}
          <form onSubmit={onRegister}>
            <input
              className="form-control mb-2"
              name="username"
              placeholder="Имя: 3–32 символа, буквы и цифры"
              required
              minLength={3}
              maxLength={32}
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              title="3–32 символа, буквы и цифры, внутри можно . _ -"
            />
            <input className="form-control mb-2" name="email" type="email" placeholder="Email" required />
            <PasswordField name="password" placeholder="Пароль от 10 символов" minLength={10} />
            <button className="btn btn-primary w-100">Создать аккаунт</button>
          </form>
        </Modal>
      )}
      {showTotpComplete && (
        <Modal title="Код 2FA" onClose={onCloseTotpComplete}>
          <p className="small text-muted mb-3">Вход через Google почти готов — введите код из приложения-аутентификатора.</p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const form = new FormData(e.target);
              onTotpComplete(form.get("code"), remember);
            }}
          >
            <input
              className="form-control mb-2"
              name="code"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              placeholder="6 цифр"
              required
              autoFocus
            />
            <div className="form-check mb-3">
              <input
                className="form-check-input"
                type="checkbox"
                id="rememberDeviceTotp"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
              />
              <label className="form-check-label" htmlFor="rememberDeviceTotp">
                Запомнить это устройство на {trustedDeviceDays} дн.
              </label>
            </div>
            <button className="btn btn-primary w-100">Подтвердить</button>
          </form>
        </Modal>
      )}
    </>
  );
}
