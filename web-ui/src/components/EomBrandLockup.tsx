import { Link } from "react-router-dom";

const EOM_LOGO_URL =
  "https://www.eomoffshore.com/wp-content/uploads/2025/08/EOM-Logo.avif";

type Props = {
  className?: string;
};

export function EomBrandLockup({ className = "" }: Props) {
  return (
    <Link className={`eom-lockup ${className}`} to="/" aria-label="Mooring Field Database home">
      <img src={EOM_LOGO_URL} alt="EOM Offshore" />
      <span className="eom-divider" aria-hidden="true" />
      <span className="database-name">Mooring Field Database</span>
    </Link>
  );
}
