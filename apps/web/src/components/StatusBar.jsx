export default function StatusBar({ status }) {
  const services = status?.services || [];
  return (
    <section className={`service-status-bar service-status-bar--${status?.state || "checking"}`}>
      <div className="container-fluid px-3 px-lg-4">
        <div className="service-status-bar__inner">
          <div className="service-status-bar__head">
            <div>
              <div className="service-status-bar__title">Статус сервисов</div>
              <div className="service-status-bar__subtitle">
                {status?.message || "Проверяем Moonez и Google Gemini…"}
              </div>
            </div>
            <a
              className="service-status-bar__link"
              href="https://status.cloud.google.com/"
              target="_blank"
              rel="noreferrer"
            >
              Google Cloud Status
            </a>
          </div>
          <div className={`service-status-bar__grid ${services.length >= 3 ? "service-status-bar__grid--triple" : ""}`}>
            {services.map((svc) => (
              <article key={svc.id} className={`service-status-card service-status-card--${svc.state || "unknown"}`}>
                <div className="service-status-card__body">
                  <div className="service-status-card__row">
                    <h3 className="service-status-card__name">{svc.short_name || svc.name}</h3>
                    <span className="service-status-card__badge">{svc.state}</span>
                  </div>
                  <p className="service-status-card__message">{svc.message}</p>
                </div>
              </article>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
