// src/components/landing/Landing.tsx
import {Link} from "react-router-dom";
// import cover from "../../assets/journeyman/vol1/Vol1Page1.jpeg?w=1182&format=jpg&quality=95&as=picture";
// import coverPortrait from "../../assets/journeyman/vol1/Vol1Page1Phone.jpeg?w=640;1182&format=avif;webp&as=picture";
import cover from "../../assets/journeyman/vol1/Vol1Page1.jpeg?w=1182&format=avif;webp;jpg&quality=85&as=picture";
import coverPortrait from "../../assets/journeyman/vol1/Vol1Page1Phone.jpeg?w=750;1170&format=avif;webp;jpg&quality=85&as=picture";
import {FullBleedHero} from "./FullBleedHero";
import "./Landing.css";

export function Landing() {
    return (
        <FullBleedHero image={cover} portrait={coverPortrait}
                       alt="Wooden stairway up Yulong Snow Mountain, Yunnan">
            <div className="landing">
                <header className="landing__masthead">
                    <h1 className="masthead">Journeyman</h1>
                    <p className="tagline">Life, Elsewhere</p>
                </header>

                <div className="caption">
                    <p className="caption__title">Yulong Snow Mountain</p>
                    <p className="caption__sub">Yunnan, China</p>
                </div>

                <Link to="/plan" className="cue">
                    Scroll to start <span aria-hidden>⌄</span>
                </Link>

                <p className="folio">No. 1</p>
            </div>
        </FullBleedHero>
    );
}