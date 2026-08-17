import { Link } from "react-router-dom";
import { Panel, Section } from "../components/ui";

export default function NotFound() {
  return (
    <Section title="Not found">
      <Panel>
        <p className="prose">
          That page does not exist.{" "}
          <Link to="/" style={{ color: "var(--accent)" }}>
            Back to the league overview
          </Link>
          .
        </p>
      </Panel>
    </Section>
  );
}
