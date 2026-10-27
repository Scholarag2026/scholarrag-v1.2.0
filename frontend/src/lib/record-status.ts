/** Record-level verification statuses as sent by the backend. */
export const RECORD_STATUSES = [
  "record_verified",
  "metadata_mismatch",
  "doi_not_found",
  "no_doi",
] as const;

export type RecordStatus = (typeof RECORD_STATUSES)[number];

export type RecordLabelKey =
  | "recordVerified"
  | "metadataMismatch"
  | "doiNotFound"
  | "noDoi"
  | "lookupFailed"
  | "pending";

/**
 * Map a wire status to its label key. A null status is a failed Crossref lookup;
 * undefined, "pending" and any unknown value fall back to pending.
 */
export function recordStatusLabelKey(status: string | null | undefined): RecordLabelKey {
  if (status === null) return "lookupFailed";
  switch (status) {
    case "record_verified":
      return "recordVerified";
    case "metadata_mismatch":
      return "metadataMismatch";
    case "doi_not_found":
      return "doiNotFound";
    case "no_doi":
      return "noDoi";
    default:
      return "pending";
  }
}

export interface VerificationCounts {
  total: number;
  record_verified: number;
  metadata_mismatch: number;
  doi_not_found: number;
  no_doi: number;
  lookup_failed: number;
}

export function verifyCompleteValues(
  r: VerificationCounts,
): Record<"recordVerified" | "metadataMismatch" | "doiNotFound" | "noDoi" | "lookupFailed", number> {
  return {
    recordVerified: r.record_verified,
    metadataMismatch: r.metadata_mismatch,
    doiNotFound: r.doi_not_found,
    noDoi: r.no_doi,
    lookupFailed: r.lookup_failed,
  };
}
