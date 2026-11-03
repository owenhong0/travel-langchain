import type {CSSProperties, ReactNode} from "react";
import "./FullBleedHero.css";

type Picture = { sources: Record<string, string>; img: { src: string; w: number; h: number } };
type Props = {
    image: Picture;
    portrait?: Picture;      // new — used on phones / portrait screens
    alt: string;
    focal?: string;
    children?: ReactNode;
};

export function FullBleedHero({image, portrait, alt, focal = "50% 50%", children}: Props) {
    return (
        <section className="fullbleed" style={{"--focal": focal} as CSSProperties}>
            <picture>
                {portrait && Object.entries(portrait.sources).map(([format, srcset]) => (
                    <source key={`p-${format}`} media="(orientation: portrait)"
                            type={`image/${format}`} srcSet={srcset} sizes="100vw"/>
                ))}
                {Object.entries(image.sources).map(([format, srcset]) => (
                    <source key={format} type={`image/${format}`} srcSet={srcset} sizes="100vw"/>
                ))}
                <img className="fullbleed__img" src={image.img.src} width={image.img.w} height={image.img.h}
                     alt={alt} loading="eager" decoding="async" fetchPriority="high"/>
            </picture>
            <div className="fullbleed__scrim" aria-hidden/>
            <div className="fullbleed__content">{children}</div>
        </section>
    );
}