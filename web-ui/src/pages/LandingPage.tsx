import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

type RevealProps = {
  children: ReactNode;
  className?: string;
  id?: string;
};

function Reveal({ children, className = "", id }: RevealProps) {
  const ref = useRef<HTMLElement | null>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { threshold: 0.14 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <section
      ref={ref}
      id={id}
      className={`reveal ${visible ? "is-visible" : ""} ${className}`}
    >
      {children}
    </section>
  );
}

export function LandingPage() {
  return (
    <main className="landing">
      <section className="hero" aria-labelledby="hero-title">
        <video
          className="hero-video"
          autoPlay
          loop
          muted
          playsInline
          preload="metadata"
          aria-hidden="true"
        >
          <source
            src="https://videos.pexels.com/video-files/855334/855334-hd_1920_1080_30fps.mp4"
            type="video/mp4"
          />
        </video>
        <div className="hero-shade" />
        <div className="hero-content">
          <p className="eyebrow light">Satellite intelligence for working waterfronts</p>
          <h1 id="hero-title">
            See the mooring field.
            <br />
            Know who runs it.
          </h1>
          <p className="hero-intro">
            Turn waterfront imagery into a clear record of harbors, operators,
            and verified contact information.
          </p>
          <div className="hero-actions">
            <Link className="button button-accent" to="/app">
              Open the map
            </Link>
          </div>
        </div>
        <p className="hero-credit">
          Harbor footage: <a href="https://www.pexels.com/video/ship-cruising-856386/">Pexels</a>
        </p>
      </section>

      <Reveal className="method-section" id="method">
        <div className="method-intro">
          <p className="eyebrow">The method</p>
          <h2>From open water to a decision-ready record.</h2>
        </div>
        <ol className="method-list">
          <li>
            <span>01</span>
            <div>
              <h3>Detect the pattern</h3>
              <p>
                Satellite imagery reveals the repeated boat arrangement that
                marks a mooring field—not simply the nearest marina.
              </p>
            </div>
          </li>
          <li>
            <span>02</span>
            <div>
              <h3>Resolve the harbor</h3>
              <p>
                Every field is anchored to its harbor, sub-area, and local
                context so the location is clear before outreach begins.
              </p>
            </div>
          </li>
          <li>
            <span>03</span>
            <div>
              <h3>Verify the operator</h3>
              <p>
                Research connects the field with harbormasters and private
                mooring service companies, with sources retained for review.
              </p>
            </div>
          </li>
        </ol>
      </Reveal>

      <Reveal className="platform-section">
        <div className="platform-aside">
          <p className="eyebrow">The workspace</p>
          <p>
            Review the geography, validate the operator, and keep a clean
            working record.
          </p>
        </div>
        <div className="platform-statement">
          <p>
            Map the field.
            <br />
            Verify the contact.
            <br />
            <em>Work from evidence.</em>
          </p>
          <Link className="button button-ink" to="/app/table">
            Open records
          </Link>
        </div>
      </Reveal>

      <footer className="landing-footer">
        <span>EOM Offshore · Mooring Field Database</span>
        <span>Waterfront intelligence, made usable.</span>
      </footer>
    </main>
  );
}
