// Side-view geometry for the two bike diagrams (drop bar and full-suspension MTB). Millimetres,
// BB at the origin, x forward, y up, drawn from ordinary real-world proportions (a 700c CX bike
// and a 29er trail bike). They show WHERE each measured point is on a bike; they are illustrative
// and never use the athlete's own numbers. Styling is by class (theme tokens live in index.html).

const f1 = (n) => Math.round(n * 10) / 10;

// path('M', x, y, 'L', x, y, 'Q', cx, cy, x, y, 'C', ...) in y-up mm -> SVG path data (y flipped).
function path(...tokens) {
  const out = [];
  let i = 0;
  while (i < tokens.length) {
    const cmd = tokens[i++];
    const n = { M: 2, L: 2, Q: 4, C: 6, Z: 0 }[cmd];
    out.push(cmd);
    for (let k = 0; k < n; k += 2) out.push(`${f1(tokens[i + k])},${f1(-tokens[i + k + 1])}`);
    i += n;
  }
  return out.join(' ');
}

function saddleShape(tail, tip) {
  const t = 30;
  return path('M', tail[0], tail[1] + 4, 'L', tip[0] - 40, tip[1] + 6, 'Q', tip[0] + 6, tip[1] + 6, tip[0], tip[1] - 8,
    'Q', tip[0] - 14, tip[1] - t, tip[0] - 70, tip[1] - t, 'L', tail[0] + 30, tail[1] - t, 'Q', tail[0] - 8, tail[1] - t, tail[0], tail[1] + 4, 'Z');
}

function dropBar() {
  const points = {
    BB: [0, 0], FA: [600, 70], RA: [-420, 70], BC: [485, 600], ST: [-70, 695], H: [575, 622],
  };
  const stt = [-158, 516];
  const htt = [395, 539];
  const htb = [435, 421];
  return {
    viewBox: '-790 -850 1760 1170',
    points,
    floor: { x0: -790, x1: 970, y: -270 },
    wheelR: 340,
    dot: 11,
    font: 54,
    frame: [
      [points.BB, stt], [points.BB, htb, 'bf-frame bf-thick'], [stt, htt], [htb, htt, 'bf-frame bf-thick'],
      [points.BB, points.RA], [stt, points.RA], [stt, [-205, 669], 'bf-frame bf-post'], [htt, [380, 580], 'bf-frame bf-thick'],
      [[380, 580], points.BC, 'bf-frame bf-thick'],
    ],
    paths: [
      { cls: 'bf-frame bf-fork', d: path('M', 435, 421, 'Q', 505, 250, 600, 70) },
      { cls: 'bf-frame bf-bar', d: path('M', 485, 600, 'L', 545, 603, 'C', 595, 606, 618, 585, 616, 545, 'C', 614, 490, 575, 455, 520, 452) },
      { cls: 'bf-hood', d: path('M', 540, 600, 'C', 552, 640, 600, 636, 610, 600, 'L', 612, 548, 'L', 585, 545, 'C', 585, 572, 565, 586, 540, 592, 'Z') },
    ],
    saddle: saddleShape([-340, 695], [-70, 695]),
    crank: [[0, 0], [25, -172]],
    extras: [`<ellipse class="bf-pedal" cx="25" cy="172" rx="48" ry="12" />`,
      `<circle class="bf-ring" cx="0" cy="0" r="86" />`],
    labels: {
      BB: [55, 95, 'start'], FA: [34, -34, 'start'], RA: [-32, -38, 'end'],
      BC: [-26, -46, 'end'], ST: [-8, -52, 'middle'], H: [20, -48, 'start'],
    },
  };
}

function fullSuspension() {
  const points = {
    BB: [0, 0], FA: [750, 37], RA: [-440, 37], BC: [463, 655], ST: [-40, 703], H: [500, 650],
  };
  const stt = [-110, 426];
  const htt = [424, 630];
  const htb = [475, 521];
  const pivot = [-25, 95];
  const rocker = [-150, 380];
  const shockTop = [110, 510];
  return {
    viewBox: '-840 -870 2000 1240',
    points,
    floor: { x0: -840, x1: 1160, y: -335 },
    wheelR: 372,
    dot: 12,
    font: 58,
    frame: [
      [points.BB, stt], [points.BB, htb, 'bf-frame bf-thick'], [stt, htt], [htb, htt, 'bf-frame bf-thick'],
      [points.BB, pivot], [pivot, points.RA], [points.RA, rocker], [rocker, shockTop, 'bf-frame bf-shock'],
      [stt, [-175, 678], 'bf-frame bf-post'], [htt, [413, 653], 'bf-frame bf-thick'], [[413, 653], points.BC, 'bf-frame bf-thick'],
      [points.BC, points.H], [[505, 640], [575, 624], 'bf-frame bf-lever'],
    ],
    paths: [
      { cls: 'bf-frame bf-fork', d: path('M', 481, 508, 'L', 665, 190) },
      { cls: 'bf-frame bf-fork bf-lower', d: path('M', 665, 190, 'L', 750, 37) },
    ],
    saddle: saddleShape([-310, 703], [-40, 703]),
    crank: [[0, 0], [25, -172]],
    extras: [`<circle class="bf-ring" cx="${pivot[0]}" cy="${-pivot[1]}" r="20" />`,
      `<circle class="bf-ring" cx="${rocker[0]}" cy="${-rocker[1]}" r="18" />`,
      `<ellipse class="bf-pedal" cx="25" cy="172" rx="48" ry="12" />`,
      `<circle class="bf-ring" cx="0" cy="0" r="80" />`,
      `<circle class="bf-grip" cx="500" cy="-650" r="28" />`],
    labels: {
      BB: [55, 95, 'start'], FA: [36, -36, 'start'], RA: [-34, -38, 'end'],
      BC: [-40, -40, 'end'], ST: [-8, -52, 'middle'], H: [40, -30, 'start'],
    },
  };
}

export const DIAGRAMS = { drop_bar: dropBar(), mtb: fullSuspension() };
