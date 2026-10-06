// Shared mutable UI state. Pages read and write ctx.<name> so that
// reassignments are visible across modules (ES module bindings are read-only).
export const ctx = {
  state: undefined,
  cfg: undefined,
  revision: undefined,
  page: "screens",
  selected: 0,
  dirty: false,
  version: 0,
  urls: [],
  toastTimer: undefined,
  previewTimer: undefined,
  editing: null,
  pano: null,
  render: () => {},
  login: () => {},
};
