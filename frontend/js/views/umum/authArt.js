// Ilustrasi statis (bukan data pengguna), jadi aman di-parse sebagai SVG. Menara = pos pantau yang memberi tanda ke rumah warga.
const SVG = `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 420 340" role="img" aria-label="Menara pos pantau memberi peringatan ke rumah-rumah warga di tepi sungai">
  <defs>
    <clipPath id="vp"><rect x="0" y="0" width="420" height="340" rx="52"/></clipPath>
    <linearGradient id="riv" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#6cc3d1"/><stop offset="1" stop-color="#0e7c86"/></linearGradient>
    <linearGradient id="hill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#a9dccb"/><stop offset="1" stop-color="#7cc4ae"/></linearGradient>
  </defs>
  <g clip-path="url(#vp)">
  <g class="par" style="--d:3">
    <circle cx="210" cy="172" r="152" fill="#d9eeeb"/>
    <circle cx="210" cy="172" r="106" fill="#c3e3dd" opacity=".75"/>
    <circle cx="64" cy="96" r="5" fill="#fff" opacity=".9"/><circle cx="364" cy="188" r="7" fill="#fff" opacity=".8"/><circle cx="120" cy="40" r="4" fill="#fff" opacity=".8"/>
  </g>
  <g class="par cloud c1" style="--d:7"><ellipse cx="82" cy="72" rx="30" ry="11" fill="#fff"/><ellipse cx="100" cy="64" rx="20" ry="10" fill="#fff"/><ellipse cx="66" cy="66" rx="14" ry="8" fill="#fff"/></g>
  <g class="par cloud c2" style="--d:10"><ellipse cx="338" cy="46" rx="26" ry="9" fill="#fff" opacity=".95"/><ellipse cx="352" cy="40" rx="16" ry="8" fill="#fff" opacity=".95"/></g>

  <g class="par" style="--d:12">
    <path d="M-40 272 Q110 226 210 256 T460 246 V400 H-40Z" fill="url(#hill)"/>
    <g class="house"><rect x="40" y="216" width="70" height="52" rx="3" fill="#fff"/><polygon points="31,218 75,184 119,218" fill="#0b3a6e"/><rect x="68" y="240" width="15" height="28" rx="2" fill="#0e7c86"/><rect x="48" y="229" width="14" height="14" rx="2" fill="#ffd27a" class="lit"/><rect x="90" y="229" width="12" height="12" rx="2" fill="#ffd27a" class="lit l2"/></g>
    <g class="house"><rect x="294" y="224" width="68" height="44" rx="3" fill="#fff"/><polygon points="285,226 328,194 371,226" fill="#17b890"/><rect x="320" y="244" width="14" height="24" rx="2" fill="#0b3a6e"/><rect x="302" y="234" width="12" height="12" rx="2" fill="#ffd27a" class="lit l2"/><rect x="342" y="234" width="12" height="12" rx="2" fill="#ffd27a" class="lit"/></g>
    <g class="house"><rect x="126" y="240" width="44" height="28" rx="2" fill="#fff"/><polygon points="119,242 148,220 177,242" fill="#0e7c86"/><rect x="142" y="252" width="11" height="16" rx="2" fill="#0b3a6e"/></g>
    <rect x="254" y="246" width="6" height="22" fill="#7a5c3a"/><circle cx="257" cy="236" r="19" fill="#0f9d6b"/><circle cx="248" cy="243" r="13" fill="#17b890"/>
  </g>

  <g class="par tower" style="--d:18">
    <polygon points="194,270 226,270 219,152 201,152" fill="#0b3a6e"/>
    <polygon points="199,196 221,196 220,208 200,208" fill="#fff" opacity=".92"/>
    <polygon points="202,232 218,232 217,244 203,244" fill="#fff" opacity=".92"/>
    <rect x="196" y="132" width="28" height="22" rx="4" fill="#ffd27a"/>
    <polygon points="191,133 210,111 229,133" fill="#0e7c86"/>
    <circle cx="210" cy="143" r="5" fill="#fff" opacity=".9"/>
    <circle class="ring r1" cx="210" cy="143" r="14" fill="none" stroke="#17b890" stroke-width="3"/>
    <circle class="ring r2" cx="210" cy="143" r="14" fill="none" stroke="#17b890" stroke-width="3"/>
    <circle class="ring r3" cx="210" cy="143" r="14" fill="none" stroke="#17b890" stroke-width="3"/>
  </g>

  <g class="par" style="--d:26">
    <g class="bell" transform="translate(352 118)">
      <g class="swing"><path d="M-13 10 Q-13 -12 0 -12 T13 10 L16 15 H-16Z" fill="#ffb020"/><circle cx="0" cy="-14" r="3" fill="#ffb020"/><circle cx="0" cy="20" r="3.4" fill="#e69500"/></g>
    </g>
    <g class="waves"><path d="M-140 296 Q-105 284 -70 296 T0 296 T70 296 T140 296 T210 296 T280 296 T350 296 T420 296 T490 296 T560 296 V400 H-140Z" fill="url(#riv)"/></g>
    <g class="waves w2"><path d="M-140 314 Q-105 304 -70 314 T0 314 T70 314 T140 314 T210 314 T280 314 T350 314 T420 314 T490 314 T560 314 V400 H-140Z" fill="#0b3a6e" opacity=".28"/></g>
  </g>
  </g>
</svg>`;

export function authIllustration() {
  return document.importNode(new DOMParser().parseFromString(SVG, "image/svg+xml").documentElement, true);
}
