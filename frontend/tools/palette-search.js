const { dE, simulate, contrast } = require("./palette.js");
const P = [["voltarget","#3987e5"],["trend","#d95926"],["defensive","#199e70"],
           ["ensemble","#c98500"],["technical","#d55181"],["ml","#008300"],
           ["macro","#9085e9"],["miners","#e66767"],["claude","#1f9aa8"],
           ["kanalfinans","#a86a2a"]];
const GROUND = "#15120d";
// Baseline of the existing ten, measured under THIS validator.
const BASE = { adjNormal: 34.9, adjPD: 14.8, adjTrit: 2.1, anyPair: 12.6, contrast: 3.78 };

const unlin=(c)=> c<=0.0031308 ? 12.92*c : 1.055*Math.pow(c,1/2.4)-0.055;
function lab2hex(L,a,b){
  const wx=0.95047,wy=1,wz=1.08883, d=6/29;
  const fy=(L+16)/116, fx=fy+a/500, fz=fy-b/200;
  const g=(t)=> t>d ? t*t*t : 3*d*d*(t-4/29);
  const X=wx*g(fx), Y=wy*g(fy), Z=wz*g(fz);
  let r= X* 3.2404542+Y*-1.5371385+Z*-0.4985314;
  let gg=X*-0.9692660+Y* 1.8760108+Z* 0.0415560;
  let bb=X* 0.0556434+Y*-0.2040259+Z* 1.0572252;
  for (const v of [r,gg,bb]) if (v < -0.001 || v > 1.001) return null;  // out of gamut
  const c=(v)=>Math.round(Math.max(0,Math.min(1,unlin(Math.max(0,Math.min(1,v)))))*255)
    .toString(16).padStart(2,"0");
  return "#"+c(r)+c(gg)+c(bb);
}

const results = [];
// Stay inside the band the existing ten occupy: L 47.3-61.0, chroma
// 31.4-73.1, contrast 3.78-6.08 on #15120d. A pale pastel scores
// beautifully on separation and then draws the eye to whichever series
// happens to own it -- brightness is not a free axis here.
for (let L = 47; L <= 61; L += 1)
 for (let C = 31; C <= 74; C += 1)
  for (let h = 0; h < 360; h += 4) {
    const hex = lab2hex(L, C*Math.cos(h*Math.PI/180), C*Math.sin(h*Math.PI/180));
    if (!hex) continue;
    const adjN = dE(P[9][1], hex);
    if (adjN < BASE.adjNormal) continue;
    const adjPD = Math.min(...["prot","deut"].map(k => dE(simulate(P[9][1],k), simulate(hex,k))));
    if (adjPD < BASE.adjPD) continue;
    const adjT = dE(simulate(P[9][1],"trit"), simulate(hex,"trit"));
    if (adjT < BASE.adjTrit) continue;
    const anyP = Math.min(...P.map(([,c]) => dE(c, hex)));
    if (anyP < BASE.anyPair) continue;
    const con = contrast(hex, GROUND);
    if (con < 3.78 || con > 6.08) continue;
    results.push({ hex, adjN, adjPD, adjT, anyP, con, L, C, h });
  }
// Rank by the weakest guarantee it offers, then by any-pair separation.
results.sort((a,b) => (Math.min(b.anyP, b.adjPD) - Math.min(a.anyP, a.adjPD)) || (b.anyP - a.anyP));
console.log("aday sayısı:", results.length);
for (const r of results.slice(0, 12)) {
  console.log(`${r.hex}  bitişik(normal) ${r.adjN.toFixed(1)}  bitişik(p/d) ${r.adjPD.toFixed(1)}`
    + `  bitişik(trit) ${r.adjT.toFixed(1)}  herhangi-çift ${r.anyP.toFixed(1)}`
    + `  kontrast ${r.con.toFixed(2)}:1   [L${r.L} C${r.C} h${r.h}]`);
}
