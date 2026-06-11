// Keeps body padding-top in sync with the actual rendered height of the fixed
// nav bar. Required because the nav wraps to more rows as more leagues load,
// making its height unpredictable at CSS authoring time.
(function () {
    function syncPadding() {
        var nav = document.querySelector('.fixed-team-nav');
        if (!nav) return;
        document.body.style.paddingTop = nav.offsetHeight + 8 + 'px';
    }
    document.addEventListener('DOMContentLoaded', syncPadding);
    window.addEventListener('resize', syncPadding);
}());
