document.addEventListener('DOMContentLoaded', function () {
    const track = document.getElementById('galleryTrack');
    const prevBtn = document.getElementById('galleryPrev');
    const nextBtn = document.getElementById('galleryNext');
    const dotsEl = document.getElementById('galleryDots');
    const creditEl = document.getElementById('galleryCredit');
    if (!track) return;

    const slides = track.querySelectorAll('.gallery-slide');
    let current = 0;

    // Build dot indicators
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
        syncCredit();
    }

    function syncCredit() {
        if (!creditEl) return;
        var slide = slides[current];
        var credit = slide ? (slide.dataset.credit || '') : '';
        if (credit) {
            creditEl.textContent = '📷 ' + credit;
            creditEl.style.display = '';
        } else {
            creditEl.textContent = '';
            creditEl.style.display = 'none';
        }
    }

    /* Rubber-band bounce when hitting the first or last slide.
       Briefly translates the track in the attempted direction, then springs back. */
    function bounceTrack(directionPx) {
        track.style.transition = 'transform 0.12s cubic-bezier(0.33, 1, 0.68, 1)';
        track.style.transform = 'translateX(' + directionPx + 'px)';
        setTimeout(function () {
            track.style.transition = 'transform 0.22s cubic-bezier(0.33, 1, 0.68, 1)';
            track.style.transform = 'translateX(0)';
            setTimeout(function () { track.style.transition = ''; }, 220);
        }, 120);
    }

    prevBtn.addEventListener('click', function () {
        if (current === 0) { bounceTrack(28); return; }  // 28px right = "can't go further left"
        goTo(current - 1);
    });
    nextBtn.addEventListener('click', function () {
        if (current === slides.length - 1) { bounceTrack(-28); return; }  // 28px left = "can't go further right"
        goTo(current + 1);
    });

    track.addEventListener('scroll', function () {
        var i = Math.round(track.scrollLeft / track.clientWidth);
        if (i !== current) { current = i; syncDots(); }
    }, { passive: true });

    if (slides.length <= 1) {
        /* Single image: hide dots, arrows visible but non-interactive.
           Clicking either arrow still triggers the bounce for tactile feedback. */
        dotsEl.style.display = 'none';
        prevBtn.style.opacity = '0.45';
        nextBtn.style.opacity = '0.45';
        /* Re-enable pointer events so the bounce fires, but goTo() won't move anywhere */
    }
});
