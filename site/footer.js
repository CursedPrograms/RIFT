// The footer every fleet site shares: footer.html and footer.css, here in one place. Each page has a
// plain <footer id="site-footer"> of its own, which stays if this can't load.
(function () {
  var base = document.currentScript.src.replace(/[^/]*$/, '');
  var repo = location.pathname.split('/')[1] || 'RIFT';
  var css = document.createElement('link');
  css.rel = 'stylesheet';
  css.href = base + 'footer.css';
  document.head.appendChild(css);
  fetch(base + 'footer.html')
    .then(function (r) { if (!r.ok) throw new Error('no footer'); return r.text(); })
    .then(function (html) {
      var slot = document.getElementById('site-footer');
      if (slot) slot.outerHTML = html.split('{{repo}}').join(repo);
    })
    .catch(function () {});
})();
