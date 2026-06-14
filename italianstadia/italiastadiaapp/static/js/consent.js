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

  function applyChoice(choice) {
    try { localStorage.setItem(CONSENT_KEY, choice); } catch (e) {}
    var banner = document.getElementById('cookie-banner');
    if (banner) {
      banner.style.transition = 'opacity 0.3s';
      banner.style.opacity = '0';
      setTimeout(function () { if (banner.parentNode) banner.parentNode.removeChild(banner); }, 320);
    }
    if (choice === 'accepted') loadAdsense();
  }

  function init() {
    var existing;
    try { existing = localStorage.getItem(CONSENT_KEY); } catch (e) {}

    if (existing === 'accepted') {
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
