import json
import re
from concurrent.futures import ThreadPoolExecutor
import anthropic
from flask import Flask, render_template, request, jsonify, Response, stream_with_context

app = Flask(__name__)

BASE_AESTHETICS_PROMPT = """You tend to converge toward generic, "on distribution" outputs. In frontend design, this creates what users call the "AI slop" aesthetic. Avoid this: make creative, distinctive frontends that surprise and delight. Focus on:

Typography: Choose fonts that are beautiful, unique, and interesting. Use Google Fonts imports. Avoid generic fonts like Arial, Inter, Roboto; opt instead for distinctive choices that elevate the frontend's aesthetics.

Color & Theme: Commit to a cohesive aesthetic. Use CSS variables for consistency. Dominant colors with sharp accents outperform timid, evenly-distributed palettes. Draw from IDE themes and cultural aesthetics for inspiration.

Motion: Use CSS animations for effects and micro-interactions. Focus on high-impact moments: one well-orchestrated page load with staggered reveals (animation-delay) creates more delight than scattered micro-interactions.

Backgrounds: Create atmosphere and depth rather than defaulting to solid colors. Layer CSS gradients, use geometric patterns, or add contextual effects that match the overall aesthetic.

Avoid generic AI-generated aesthetics:
- Overused font families (Inter, Roboto, Arial, system fonts, Space Grotesk)
- Clichéd color schemes (particularly purple gradients on white backgrounds)
- Predictable layouts and component patterns
- Cookie-cutter design that lacks context-specific character

Interpret creatively and make unexpected choices that feel genuinely designed for the context. Vary between light and dark themes, different fonts, different aesthetics. Think outside the box!"""

VARIATION_DIRECTIONS = [
    "Create a DARK, moody aesthetic — think deep backgrounds (#0a0a0f range), glowing accents, sleek typography. Inspired by premium fintech dashboards, IDE themes like Dracula/One Dark, or luxury automotive interfaces.",
    "Create a LIGHT, editorial aesthetic — think warm whites, sophisticated serif+sans pairings, generous whitespace, and subtle paper-like textures. Inspired by high-end magazine layouts, Scandinavian design, or Japanese minimalism.",
    "Create a BOLD, colorful aesthetic — think saturated dominant color, strong geometric shapes, playful but professional. Inspired by Bauhaus, Memphis design, or modern brand identities like Stripe/Linear/Vercel but with unexpected color choices.",
]

BRAND_SYSTEM = "You are an elite brand designer and creative director. You create distinctive, memorable visual identities for digital products. You never default to safe, generic choices — you make bold, cohesive decisions that feel intentional and unique to each product."

PAGE_GENERATION_RULES = """CONTEXT: These mockups will be used as portfolio screenshots to impress potential clients. They must look like real, polished, shipped products — not student projects or templates.

CRITICAL RULES:
1. Return ONLY the raw HTML. No markdown, no code fences, no explanation.
2. Each page must be a complete standalone HTML document with embedded CSS and Google Fonts imports via <link> tags.
3. Use realistic placeholder data (names, numbers, dates, etc.) that matches the SaaS context. Fill every section with convincing content — no "lorem ipsum" or empty placeholders.
4. Pages are static visual mockups — no JavaScript needed, no functionality.
5. Make the design feel like a real shipped product that a well-funded startup would have.
6. Every page must share the SAME design language — same fonts, same CSS variables, same color palette, same spacing and border-radius conventions.
7. Pages should be DENSE with content and visual detail — data-rich dashboards, populated tables, filled-out cards, realistic charts (use CSS/SVG). Empty-looking pages are unacceptable for portfolio use."""


def call_anthropic(api_key, system_prompt, user_message, max_tokens=16000):
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return message.content[0].text


def clean_html(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```html?\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def extract_json(text):
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        return json.loads(match.group(0))
    return json.loads(text)


def generate_one_variation(api_key, idea, app_name, direction_hint, variation_index):
    """Generate one aesthetics prompt + landing page for a variation."""
    # Step A: Customize aesthetics
    aesthetics = call_anthropic(
        api_key,
        BRAND_SYSTEM,
        f"""I have a SaaS app idea:
"{idea}"
App name: "{app_name}"

{direction_hint}

Below is a generic frontend aesthetics guide. Your job is to CUSTOMIZE it specifically for this SaaS idea with the aesthetic direction above. Produce a tailored version that:
- Picks specific Google Fonts that match the mood/industry of this SaaS (give exact font names)
- Defines a specific color palette with exact hex codes (primary, secondary, accent, background, text colors)
- Specifies exact CSS variable definitions to use
- Describes the specific mood, spacing rhythm, border-radius style, and shadow approach
- Describes specific background treatments (gradients, patterns, textures) to use

Here is the base guide to customize:

{BASE_AESTHETICS_PROMPT}

Return ONLY the customized aesthetics prompt as plain text (no JSON, no markdown fences). It should be a self-contained design specification document that another AI can follow to build consistent pages.""",
        max_tokens=4000,
    ).strip()

    # Step B: Generate landing page using that aesthetics
    generation_system = f"""You are an expert frontend developer who creates production-ready HTML/CSS page mockups for SaaS applications. Your pages are meant to be used as screenshot material — they must look polished, realistic, and visually striking.

Follow this design specification EXACTLY:

{aesthetics}

{PAGE_GENERATION_RULES}"""

    landing_html = call_anthropic(
        api_key,
        generation_system,
        f"""SaaS idea: "{idea}"
App name: "{app_name}"

Generate the "Landing Page" as a complete, standalone HTML document.

This will be used as a portfolio screenshot to win client projects. It MUST look impressive.

Requirements:
- Complete <!DOCTYPE html> document with all CSS embedded in <style> tags
- Import Google Fonts via <link> tags in the <head>
- Use the EXACT CSS variables, fonts, and color palette from the design specification in your system prompt
- DENSE, realistic content — fill every section with convincing placeholder data (real-sounding names, plausible numbers, realistic dates). No empty sections or lorem ipsum.
- Designed at 1440px wide desktop viewport
- Must look like a screenshot of a real product built by a top-tier design agency
- Include hero, features, social proof with company names, testimonials, CTA sections

Return ONLY the raw HTML. No markdown fences, no explanation.""",
    )

    return {
        "index": variation_index,
        "aesthetics": aesthetics,
        "html": clean_html(landing_html),
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/variations", methods=["POST"])
def generate_variations():
    """Step 1: Generate app name + 3 landing page variations in parallel."""
    data = request.get_json()
    api_key = data.get("apiKey", "").strip()
    idea = data.get("idea", "").strip()

    if not api_key:
        return jsonify({"error": "API key is required"}), 400
    if not idea:
        return jsonify({"error": "SaaS idea is required"}), 400

    def event_stream():
        try:
            # First: get app name + page plan
            yield json.dumps({"step": "planning", "message": "Planning your app…"}) + "\n"

            plan_response = call_anthropic(
                api_key,
                "You are a SaaS product strategist specializing in portfolio presentation. You select pages that will impress potential clients viewing a developer/designer's portfolio.",
                f"""SaaS idea: "{idea}"

These page mockups will be used as portfolio screenshots to attract potential clients. Pick 3 to 5 pages that are the most visually impressive and demonstrate strong product design.

Rules:
- The FIRST page MUST always be "Landing Page"
- The remaining 2-4 pages should be the most interesting, data-rich, or visually complex pages for THIS specific SaaS
- Avoid boring pages like plain settings, empty states, or simple forms
- Choose pages specific to THIS product's domain

Also invent a creative, memorable app name for this product.

Respond in this exact JSON format only, no other text:
{{
  "appName": "...",
  "pages": ["Landing Page", "Page Name 2", ...]
}}""",
                max_tokens=1000,
            )

            plan = extract_json(plan_response)
            app_name = plan.get("appName", "SaaSApp")
            page_list = plan.get("pages", ["Landing Page", "Dashboard", "Pricing"])[:5]

            # Ensure Landing Page is first
            landing_idx = next(
                (i for i, p in enumerate(page_list) if "landing" in p.lower()), -1
            )
            if landing_idx > 0:
                lp = page_list.pop(landing_idx)
                page_list.insert(0, lp)
            elif landing_idx == -1:
                page_list.insert(0, "Landing Page")

            fillers = ["Dashboard", "Pricing"]
            for f in fillers:
                if len(page_list) >= 3:
                    break
                if f not in page_list:
                    page_list.append(f)
            page_list = page_list[:5]

            yield json.dumps({"step": "plan_ready", "appName": app_name, "pages": page_list}) + "\n"

            # Generate 3 variations in parallel
            yield json.dumps({"step": "generating_variations", "message": "Generating 3 design variations…"}) + "\n"

            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = [
                    executor.submit(
                        generate_one_variation, api_key, idea, app_name, direction, i
                    )
                    for i, direction in enumerate(VARIATION_DIRECTIONS)
                ]

                for future in futures:
                    result = future.result()
                    yield json.dumps({
                        "step": "variation_ready",
                        "index": result["index"],
                        "aesthetics": result["aesthetics"],
                        "html": result["html"],
                    }) + "\n"

            yield json.dumps({"step": "variations_done"}) + "\n"

        except anthropic.APIError as e:
            yield json.dumps({"step": "error", "message": str(e)}) + "\n"
        except json.JSONDecodeError:
            yield json.dumps({"step": "error", "message": "Failed to parse AI response. Please try again."}) + "\n"
        except Exception as e:
            yield json.dumps({"step": "error", "message": str(e)}) + "\n"

    return Response(
        stream_with_context(event_stream()),
        mimetype="application/x-ndjson",
    )


@app.route("/api/generate-pages", methods=["POST"])
def generate_remaining_pages():
    """Step 2: Using the chosen aesthetics, generate the remaining pages."""
    data = request.get_json()
    api_key = data.get("apiKey", "").strip()
    idea = data.get("idea", "").strip()
    app_name = data.get("appName", "").strip()
    aesthetics = data.get("aesthetics", "").strip()
    page_list = data.get("pages", [])

    if not api_key or not idea or not aesthetics or not page_list:
        return jsonify({"error": "Missing required fields"}), 400

    # Remove Landing Page since user already has it
    remaining = [p for p in page_list if "landing" not in p.lower()]

    def event_stream():
        try:
            generation_system = f"""You are an expert frontend developer who creates production-ready HTML/CSS page mockups for SaaS applications. Your pages are meant to be used as screenshot material — they must look polished, realistic, and visually striking.

Follow this design specification EXACTLY:

{aesthetics}

{PAGE_GENERATION_RULES}"""

            generated_descriptions = [
                f"- Landing Page: completed with consistent {app_name} branding and shared design tokens"
            ]

            for i, page_name in enumerate(remaining):
                yield json.dumps({
                    "step": "generating",
                    "message": f"Generating {page_name}…",
                    "pageIndex": i,
                    "totalPages": len(remaining),
                }) + "\n"

                prev_context = "Previously generated pages (you MUST maintain the exact same design language — same fonts, colors, CSS variables, spacing):\n" + "\n".join(generated_descriptions) + "\n\n"

                html = call_anthropic(
                    api_key,
                    generation_system,
                    f"""SaaS idea: "{idea}"
App name: "{app_name}"

{prev_context}Generate the "{page_name}" page as a complete, standalone HTML document.

This will be used as a portfolio screenshot to win client projects. It MUST look impressive.

Requirements:
- Complete <!DOCTYPE html> document with all CSS embedded in <style> tags
- Import Google Fonts via <link> tags in the <head>
- Use the EXACT CSS variables, fonts, and color palette from the design specification in your system prompt
- DENSE, realistic content — fill every section with convincing placeholder data (real-sounding names, plausible numbers, realistic dates). No empty sections or lorem ipsum.
- Designed at 1440px wide desktop viewport
- Must look like a screenshot of a real product built by a top-tier design agency
- For dashboards/data pages: include populated charts (CSS/SVG), filled tables, stat cards with real numbers, activity feeds
- MUST use the same CSS variables, fonts, and design tokens as previous pages

Return ONLY the raw HTML. No markdown fences, no explanation.""",
                )

                clean = clean_html(html)

                yield json.dumps({
                    "step": "page_ready",
                    "pageIndex": i,
                    "pageName": page_name,
                    "html": clean,
                }) + "\n"

                generated_descriptions.append(
                    f"- {page_name}: completed with consistent {app_name} branding and shared design tokens"
                )

            yield json.dumps({"step": "done"}) + "\n"

        except anthropic.APIError as e:
            yield json.dumps({"step": "error", "message": str(e)}) + "\n"
        except Exception as e:
            yield json.dumps({"step": "error", "message": str(e)}) + "\n"

    return Response(
        stream_with_context(event_stream()),
        mimetype="application/x-ndjson",
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
