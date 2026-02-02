import os
import json
import re
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


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.get_json()
    api_key = data.get("apiKey", "").strip()
    idea = data.get("idea", "").strip()

    if not api_key:
        return jsonify({"error": "API key is required"}), 400
    if not idea:
        return jsonify({"error": "SaaS idea is required"}), 400

    def event_stream():
        try:
            # ── Step 1: Customize aesthetics prompt ──
            yield json.dumps({"step": "aesthetics", "message": "Crafting a unique design identity…"}) + "\n"

            customized_prompt = call_anthropic(
                api_key,
                "You are an elite brand designer and creative director. You create distinctive, memorable visual identities for digital products. You never default to safe, generic choices — you make bold, cohesive decisions that feel intentional and unique to each product.",
                f"""I have a SaaS app idea:
"{idea}"

Below is a generic frontend aesthetics guide. Your job is to CUSTOMIZE it specifically for this SaaS idea. Produce a tailored version that:
- Picks specific Google Fonts that match the mood/industry of this SaaS (give exact font names)
- Defines a specific color palette with exact hex codes (primary, secondary, accent, background, text colors) that feels right for this domain
- Chooses a specific aesthetic direction (not generic — something like "warm editorial with craft textures" or "clinical Swiss design with mint accents" or "dark observatory dashboard with amber data-glow") that suits this product
- Specifies exact CSS variable definitions to use
- Describes the specific mood, spacing rhythm, border-radius style, and shadow approach
- Describes specific background treatments (gradients, patterns, textures) to use

Here is the base guide to customize:

{BASE_AESTHETICS_PROMPT}

Return ONLY the customized aesthetics prompt as plain text (no JSON, no markdown fences). It should be a self-contained design specification document that another AI can follow to build consistent pages.""",
                max_tokens=4000,
            )
            customized_prompt = customized_prompt.strip()

            # ── Step 2: Plan pages ──
            yield json.dumps({"step": "planning", "message": "Planning pages…"}) + "\n"

            plan_response = call_anthropic(
                api_key,
                "You are a SaaS product strategist specializing in portfolio presentation. You select pages that will impress potential clients viewing a developer/designer's portfolio. The screenshots need to demonstrate technical skill, design taste, and product thinking.",
                f"""SaaS idea: "{idea}"

These page mockups will be used as portfolio screenshots to attract potential clients. Pick 3 to 5 pages that are the most visually impressive and demonstrate strong product design.

Rules:
- The FIRST page MUST always be "Landing Page" — this is the hero piece of any portfolio showcase
- The remaining 2-4 pages should be the most interesting, data-rich, or visually complex pages for THIS specific SaaS — things like dashboards with charts, detailed feature views, rich data tables, calendar/scheduling views, analytics screens, etc.
- Avoid boring pages like plain settings, empty states, or simple forms — pick pages that wow a client when they see the screenshot
- Choose pages specific to THIS product's domain (e.g. a fitness app needs a workout tracker view, a finance app needs a portfolio/transactions screen)

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

            # Enforce 3-5 range
            fillers = ["Dashboard", "Pricing"]
            for f in fillers:
                if len(page_list) >= 3:
                    break
                if f not in page_list:
                    page_list.append(f)
            page_list = page_list[:5]

            yield json.dumps({"step": "plan_ready", "appName": app_name, "pages": page_list}) + "\n"

            # ── Step 3: Generate each page ──
            generation_system = f"""You are an expert frontend developer who creates production-ready HTML/CSS page mockups for SaaS applications. Your pages are meant to be used as screenshot material — they must look polished, realistic, and visually striking.

Follow this design specification EXACTLY:

{customized_prompt}

CONTEXT: These mockups will be used as portfolio screenshots to impress potential clients. They must look like real, polished, shipped products — not student projects or templates.

CRITICAL RULES:
1. Return ONLY the raw HTML. No markdown, no code fences, no explanation.
2. Each page must be a complete standalone HTML document with embedded CSS and Google Fonts imports via <link> tags.
3. Use realistic placeholder data (names, numbers, dates, etc.) that matches the SaaS context. Fill every section with convincing content — no "lorem ipsum" or empty placeholders.
4. Pages are static visual mockups — no JavaScript needed, no functionality.
5. Make the design feel like a real shipped product that a well-funded startup would have.
6. Every page must share the SAME design language — same fonts, same CSS variables, same color palette, same spacing and border-radius conventions.
7. Pages should be DENSE with content and visual detail — data-rich dashboards, populated tables, filled-out cards, realistic charts (use CSS/SVG). Empty-looking pages are unacceptable for portfolio use."""

            generated_descriptions = []

            for i, page_name in enumerate(page_list):
                yield json.dumps({
                    "step": "generating",
                    "message": f"Generating {page_name}…",
                    "pageIndex": i,
                    "totalPages": len(page_list),
                }) + "\n"

                prev_context = ""
                if generated_descriptions:
                    prev_context = f"Previously generated pages (you MUST maintain the exact same design language — same fonts, colors, CSS variables, spacing):\n" + "\n".join(generated_descriptions) + "\n\n"

                consistency_rule = ""
                if generated_descriptions:
                    consistency_rule = "- MUST use the same CSS variables, fonts, and design tokens as previous pages"

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
- For landing pages: include hero, features, social proof with company names, testimonials, CTA sections
{consistency_rule}

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
        except json.JSONDecodeError:
            yield json.dumps({"step": "error", "message": "Failed to parse AI response. Please try again."}) + "\n"
        except Exception as e:
            yield json.dumps({"step": "error", "message": str(e)}) + "\n"

    return Response(
        stream_with_context(event_stream()),
        mimetype="application/x-ndjson",
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
