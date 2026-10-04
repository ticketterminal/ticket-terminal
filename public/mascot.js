// Casey, Ticket Terminal's stationmaster — a small helper character used in
// the categories onboarding dialog and the Help popup. Original artwork
// (user-generated, not derived from any existing game/character), shipped as
// a static sprite at public/assets/mascot-conductor.png.
export const MASCOT_NAME = "Casey";

// `body` is a DOM node, an array of DOM nodes, or a plain string (rendered as
// one paragraph) making up the speech bubble's content next to Casey.
export function mascotSay(body){
  const wrap = document.createElement("div");
  wrap.className = "mascotwrap";
  const figure = document.createElement("div");
  figure.className = "mascotfigure";
  const img = document.createElement("img");
  img.className = "mascotimg";
  img.src = "/static/assets/mascot-conductor.png";
  img.width = 241;
  img.height = 320;
  img.alt = "";
  img.setAttribute("aria-hidden", "true");
  figure.appendChild(img);
  wrap.appendChild(figure);
  const bubble = document.createElement("div");
  bubble.className = "mascotbubble";
  bubble.setAttribute("role", "note");
  bubble.setAttribute("aria-label", MASCOT_NAME);
  if (typeof body === "string"){
    const p = document.createElement("p");
    p.textContent = body;
    bubble.appendChild(p);
  } else {
    (Array.isArray(body) ? body : [body]).forEach(node => bubble.appendChild(node));
  }
  wrap.appendChild(bubble);
  return wrap;
}
