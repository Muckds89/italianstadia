document.addEventListener('DOMContentLoaded', function () {
    const track = document.getElementById('galleryTrack');
    const prevBtn = document.getElementById('galleryPrev');
    const nextBtn = document.getElementById('galleryNext');
    const dotsEl = document.getElementById('galleryDots');
    if (!track) return;

    const slides = track.querySelectorAll('.gallery-slide');
    let current = 0;

    slides.forEach(function (_, i) {
        const dot = document.createElement('button');
        dot.className = 'gallery-dot' + (i === 0 ? ' active' : '');
        dot.setAttribute('aria-label', 'Slide ' + (i + 1));
        dot.addEventListener('click', function () { goTo(i); });
        dotsEl.appendChild(dot);
    });

    function goTo(i) {
        current = Math.max(0, Math.min(i, slides.length - 1));
        track.scrollTo({ left: current * track.clientWidth, behavior: 'smooth' });
        syncDots();
    }

    function syncDots() {
        dotsEl.querySelectorAll('.gallery-dot').forEach(function (d, i) {
            d.classList.toggle('active', i === current);
        });
    }

    prevBtn.addEventListener('click', function () { goTo(current - 1); });
    nextBtn.addEventListener('click', function () { goTo(current + 1); });

    track.addEventListener('scroll', function () {
        const i = Math.round(track.scrollLeft / track.clientWidth);
        if (i !== current) { current = i; syncDots(); }
    }, { passive: true });

    if (slides.length <= 1) {
        prevBtn.style.display = 'none';
        nextBtn.style.display = 'none';
        dotsEl.style.display = 'none';
    }
});
