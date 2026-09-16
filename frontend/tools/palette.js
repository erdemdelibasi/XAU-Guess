/* Palette validator. Run this instead of choosing a hue by eye.
 *
 * CIEDE2000 between adjacent legend slots -- adjacency is what matters,
 * because that is the pair a reader compares -- under normal vision and under
 * Vienot/Brettel/Mollon dichromacy simulation, plus WCAG contrast on the
 * card ground (#15120d). Prints the four worst cases.
 *
 *   node frontend/tools/palette.js '[["voltarget","#3987e5"], ...]'
 *
 * Pass chart.js's SERIES_COLOURS in LEGEND ORDER (app.js LIVE_SERIES), since
 * reordering the legend changes which hues sit next to each other. The rule
 * for a new slot: it must not make any of the four figures WORSE. Measured
 * for the current eleven (2026-09-16): adjacent normal 34.9, adjacent
 * colour-blind 2.1, closest of any pair 12.6, lowest contrast 3.78:1 --
 * identical to the ten before `breakout` was appended, which is the point.
 *
 * These numbers are NOT on the same scale as the ones recorded in CLAUDE.md
 * for slots 1-10; that was a different tool. Compare them to each other.
 *
 * palette-search.js sweeps the gamut for candidates under these constraints.
 */
const hex = (h) => [1,3,5].map((i)=>parseInt(h.slice(i,i+2),16)/255);
const lin = (c)=> c<=0.04045 ? c/12.92 : Math.pow((c+0.055)/1.055,2.4);
const unlin=(c)=> c<=0.0031308 ? 12.92*c : 1.055*Math.pow(c,1/2.4)-0.055;
function rgb2xyz(r,g,b){r=lin(r);g=lin(g);b=lin(b);return[
 r*0.4124564+g*0.3575761+b*0.1804375,
 r*0.2126729+g*0.7151522+b*0.0721750,
 r*0.0193339+g*0.1191920+b*0.9503041];}
function xyz2lab(x,y,z){const wx=0.95047,wy=1,wz=1.08883;
 const f=(t)=> t>Math.pow(6/29,3)? Math.cbrt(t) : t/(3*Math.pow(6/29,2))+4/29;
 const fx=f(x/wx),fy=f(y/wy),fz=f(z/wz);
 return [116*fy-16,500*(fx-fy),200*(fy-fz)];}
const lab = (h)=>xyz2lab(...rgb2xyz(...hex(h)));
function dE2000(L1,a1,b1,L2,a2,b2){
 const rad=Math.PI/180,deg=180/Math.PI;
 const C1=Math.hypot(a1,b1),C2=Math.hypot(a2,b2),Cb=(C1+C2)/2;
 const G=0.5*(1-Math.sqrt(Math.pow(Cb,7)/(Math.pow(Cb,7)+Math.pow(25,7))));
 const a1p=(1+G)*a1,a2p=(1+G)*a2;
 const C1p=Math.hypot(a1p,b1),C2p=Math.hypot(a2p,b2);
 let h1p=Math.atan2(b1,a1p)*deg; if(h1p<0)h1p+=360;
 let h2p=Math.atan2(b2,a2p)*deg; if(h2p<0)h2p+=360;
 const dLp=L2-L1,dCp=C2p-C1p;
 let dhp=0; if(C1p*C2p!==0){dhp=h2p-h1p; if(dhp>180)dhp-=360; if(dhp<-180)dhp+=360;}
 const dHp=2*Math.sqrt(C1p*C2p)*Math.sin(dhp*rad/2);
 const Lbp=(L1+L2)/2,Cbp=(C1p+C2p)/2;
 let hbp=h1p+h2p; if(C1p*C2p!==0){ if(Math.abs(h1p-h2p)>180) hbp+= (hbp<360?360:-360); hbp/=2;} else hbp=h1p+h2p;
 const T=1-0.17*Math.cos((hbp-30)*rad)+0.24*Math.cos(2*hbp*rad)
        +0.32*Math.cos((3*hbp+6)*rad)-0.20*Math.cos((4*hbp-63)*rad);
 const dTh=30*Math.exp(-Math.pow((hbp-275)/25,2));
 const Rc=2*Math.sqrt(Math.pow(Cbp,7)/(Math.pow(Cbp,7)+Math.pow(25,7)));
 const Sl=1+(0.015*Math.pow(Lbp-50,2))/Math.sqrt(20+Math.pow(Lbp-50,2));
 const Sc=1+0.045*Cbp, Sh=1+0.015*Cbp*T;
 const Rt=-Math.sin(2*dTh*rad)*Rc;
 return Math.sqrt(Math.pow(dLp/Sl,2)+Math.pow(dCp/Sc,2)+Math.pow(dHp/Sh,2)
        +Rt*(dCp/Sc)*(dHp/Sh));}
const dE = (h1,h2)=>dE2000(...lab(h1),...lab(h2));
// Viénot/Brettel/Mollon 1999 dichromat simulation in linear LMS.
function simulate(h, kind){
 let [r,g,b]=hex(h).map(lin);
 const L=17.8824*r+43.5161*g+4.11935*b, M=3.45565*r+27.1554*g+3.86714*b,
       S=0.0299566*r+0.184309*g+1.46709*b;
 let L2=L,M2=M,S2=S;
 if(kind==="prot") L2=2.02344*M-2.52581*S;
 if(kind==="deut") M2=0.494207*L+1.24827*S;
 if(kind==="trit") S2=-0.395913*L+0.801109*M;
 let R= 0.0809444479*L2-0.130504409*M2+0.116721066*S2;
 let G=-0.0102485335*L2+0.0540193266*M2-0.113614708*S2;
 let B=-0.000365296938*L2-0.00412161469*M2+0.693511405*S2;
 const c=(v)=>Math.round(Math.max(0,Math.min(1,unlin(Math.max(0,Math.min(1,v)))))*255)
   .toString(16).padStart(2,"0");
 return "#"+c(R)+c(G)+c(B);}
const lum=(h)=>{const[r,g,b]=hex(h).map(lin);return 0.2126*r+0.7152*g+0.0722*b;};
const contrast=(a,b)=>{const l1=lum(a),l2=lum(b);
 return (Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05);};
module.exports = { dE, simulate, contrast };

if (require.main === module) {
  const GROUND = "#15120d";
  const order = JSON.parse(process.argv[2]);   // [[name,hex],...] in legend order
  let worstAdj = Infinity, worstAdjPair = "", worstCB = Infinity, worstCBPair = "";
  let worstAny = Infinity, worstAnyPair = "";
  for (let i = 0; i < order.length; i++) {
    for (let j = i + 1; j < order.length; j++) {
      const d = dE(order[i][1], order[j][1]);
      if (d < worstAny) { worstAny = d; worstAnyPair = order[i][0] + "/" + order[j][0]; }
      if (j === i + 1) {
        if (d < worstAdj) { worstAdj = d; worstAdjPair = order[i][0] + "/" + order[j][0]; }
        for (const k of ["prot", "deut", "trit"]) {
          const dc = dE(simulate(order[i][1], k), simulate(order[j][1], k));
          if (dc < worstCB) { worstCB = dc; worstCBPair = order[i][0] + "/" + order[j][0] + " " + k; }
        }
      }
    }
  }
  const lowC = order.map(([n, h]) => [n, contrast(h, GROUND)])
                    .sort((a, b) => a[1] - b[1])[0];
  console.log("bitişik en kötü dE (normal):", worstAdj.toFixed(1), worstAdjPair);
  console.log("bitişik en kötü dE (renk körü):", worstCB.toFixed(1), worstCBPair);
  console.log("herhangi çift en kötü dE:", worstAny.toFixed(1), worstAnyPair);
  console.log("en düşük kontrast (#15120d):", lowC[1].toFixed(2) + ":1", lowC[0]);
}
