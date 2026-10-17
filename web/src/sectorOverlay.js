// State transitions for the full-screen "Course sectors" overlay. Pure: main.js applies the result to
// `state` and owns the history entry / scroll restore. The overlay edits the same selection and map
// view the in-page section uses, so closing simply clears them.

export const createSectorOverlay = () => ({ open: false, scrollY: 0 });

/** `sector` is the tapped sector, or null for the Expand button. `scrollY` is the page scroll to restore. */
export function openSectorOverlay(sector, scrollY) {
  return {
    overlay: { open: true, scrollY },
    selectedSector: sector === null || sector === undefined ? null : Number(sector),
    mapView: null,
  };
}

/** Inside the overlay a tap always selects (the in-page toggle-off would blank the summary). */
export const switchOverlaySector = (_current, tapped) => Number(tapped);

export function closeSectorOverlay(overlay) {
  return { overlay: { open: false, scrollY: overlay.scrollY }, selectedSector: null, mapView: null };
}
