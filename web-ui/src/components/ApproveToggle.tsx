import type { FieldRow } from "../api/types";
import { useApprove } from "../hooks/useFields";

type Props = {
  row: FieldRow;
};

export function ApproveToggle({ row }: Props) {
  const approve = useApprove();
  if (row.prospect_id == null) {
    return <span className="muted">—</span>;
  }
  const checked = Boolean(row.approved);
  return (
    <label className="approve-toggle" title="Approve prospect">
      <input
        type="checkbox"
        checked={checked}
        disabled={approve.isPending}
        onChange={(e) =>
          approve.mutate({ id: row.prospect_id!, approved: e.target.checked })
        }
      />
      <span>{checked ? "Yes" : "No"}</span>
    </label>
  );
}
