import { create } from "zustand";

type SelectionState = {
  selectedFieldId: number | null;
  selectedProspectId: number | null;
  setField: (fieldId: number | null, prospectId?: number | null) => void;
  clear: () => void;
};

export const useSelection = create<SelectionState>((set) => ({
  selectedFieldId: null,
  selectedProspectId: null,
  setField: (fieldId, prospectId = null) =>
    set({ selectedFieldId: fieldId, selectedProspectId: prospectId }),
  clear: () => set({ selectedFieldId: null, selectedProspectId: null }),
}));
