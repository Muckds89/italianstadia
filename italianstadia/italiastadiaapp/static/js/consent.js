(function () {
  var CONSENT_KEY = 'cookie_consent';
  var CLIENT = document.documentElement.dataset.adsenseClient || '';

  function loadAdsense() {
    if (!CLIENT) return;
    var s = document.createElement('script');
    s.async = true;
    s.src = 'https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=' + CLIENT;
    s.crossOrigin = 'anonymous';
    document.head.appendChild(s);
  }

  // Google Analytics (Consent Mode v2): the GA tag is injected site-wide and defaults
  // to 'denied' (cookieless). Granting here upgrades it to full, cookie-based analytics.
  function updateAnalyticsConsent(granted) {
    if (typeof window.gtag !== 'function') return;
    var state = granted ? 'granted' : 'denied';
    window.gtag('consent', 'update', {
      analytics_storage: state,
      ad_storage: state,
      ad_user_data: state,
      ad_personalization: state
    });
  }

  function applyChoice(choice) {
    try { localStorage.setItem(CONSENT_KEY, choice); } catch (e) {}
    var banner = document.getElementById('cookie-banner');
    if (banner) {
      banner.style.transition = 'opacity 0.3s';
      banner.style.opacity = '0';
      setTimeout(function () { if (banner.parentNode) banner.parentNode.removeChild(banner); }, 320);
    }
    updateAnalyticsConsent(choice === 'accepted');
    if (choice === 'accepted') loadAdsense();
  }

  function init() {
    var existing;
    try { existing = localStorage.getItem(CONSENT_KEY); } catch (e) {}

    if (existing === 'accepted') {
      updateAnalyticsConsent(true);
      loadAdsense();
      return;
    }
    if (existing === 'rejected') return;

    // No choice yet — show banner
    var banner = document.getElementById('cookie-banner');
    if (banner) banner.classList.remove('d-none');

    var acceptBtn = document.getElementById('cookie-accept');
    var rejectBtn = document.getElementById('cookie-reject');
    if (acceptBtn) acceptBtn.addEventListener('click', function () { applyChoice('accepted'); });
    if (rejectBtn) rejectBtn.addEventListener('click', function () { applyChoice('rejected'); });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
