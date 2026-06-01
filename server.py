"""
ClaimRight — Vercel serverless entry point.
Serves the FastAPI backend + lightweight chat UI from one handler.
Open-ended conversation flow: greet → narrow → inform.
"""
import os
import sys
import re

# Ensure knowledge base is findable
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
if os.path.exists(os.path.join(BASE_DIR, "knowledge")):
    os.chdir(BASE_DIR)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional

from bot import classify_incident, get_relevant_knowledge, load_kb_json, DISCLAIMER
from knowledge import load_kb_json as kb_load

app = FastAPI(title="ClaimRight", version="0.1.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ChatRequest(BaseModel):
    message: str
    state: str = "greeting"
    scenario: Optional[str] = None
    policy_type: Optional[str] = None
    location: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    state: str
    scenario: Optional[str] = None
    policy_type: Optional[str] = None
    location: Optional[str] = None
    has_summary: bool = False


# ─── Helpers ───

def strip_context(text: str) -> str:
    return re.sub(r'^\[Scenario:[^\]]+, Policy:[^\]]+, Location:[^\]]+\]\s*', '', text)


def detect_scenario_from_text(text: str):
    """Detect scenario from text. Returns None for casual/greeting messages."""
    text_lower = text.lower().strip()
    
    # Block greeting/filler words from being classified
    if re.match(r'^(hi|hello|hey|howdy|greetings|good\s+(morning|afternoon|evening|night)|namaste|kya\s+haal|kaise\s+ho|sup|yo|hola|bonjour)\s*$', text_lower):
        return None
    if text_lower in ['hi', 'hello', 'hey', 'hmm', 'ok', 'okay', 'yes', 'no', 'sure', 'thats', 'cool', 'nice']:
        return None
    if len(text_lower) <= 2:
        return None
    
    keywords = {
        "accident": "own_damage", "collision": "own_damage", "crash": "own_damage",
        "theft": "theft", "stolen": "theft", "vehicle_theft": "theft",
        "third_party": "third_party", "third_party_damage": "third_party",
        "flood": "natural_calamity", "cyclone": "natural_calamity",
        "earthquake": "natural_calamity", "natural": "natural_calamity",
        "hit_and_run": "hit_and_run", "hitandrun": "hit_and_run",
        "hit.*ran": "hit_and_run", "hit someone": "third_party",
        "denied": "denied_claim", "rejected": "denied_claim",
        "ncb": "ncb", "no claim bonus": "ncb",
        "cashless": "cashless_reimbursement", "reimbursement": "cashless_reimbursement",
        "surveyor": "surveyor_dispute",
        "total loss": "total_loss", "write.off": "total_loss", "write-off": "total_loss",
    }
    for kw, scen in keywords.items():
        # Use regex search for patterns, substring match for plain strings
        if kw in text_lower:
            return scen
    # Regex fallback for pattern-based matches
    for kw, scen in keywords.items():
        if re.search(kw, text_lower):
            return scen
    return classify_incident(text)


def detect_policy(text: str, current: Optional[str] = None) -> Optional[str]:
    text_lower = text.lower()
    if "third-party" in text_lower or "third party" in text_lower or (current is None and "only" in text_lower and "comprehensive" not in text_lower):
        return "Third-Party Only"
    if "comprehensive" in text_lower or "compre" in text_lower or (current is None and "policy" not in text_lower and len(text) > 5):
        return "Comprehensive"
    return current


def detect_location(text: str, current: Optional[str] = None) -> Optional[str]:
    if current:
        return current
    city_map = {
        "mumbai": "Mumbai", "delhi": "Delhi", "bangalore": "Bengaluru", "bengaluru": "Bengaluru",
        "chennai": "Chennai", "hyderabad": "Hyderabad", "kolkata": "Kolkata", "pune": "Pune",
        "ahmedabad": "Ahmedabad", "kochi": "Kochi", "jaipur": "Jaipur", "lucknow": "Lucknow",
    }
    text_lower = text.lower()
    for kw, city in city_map.items():
        if kw in text_lower:
            return city
    return None


def get_scenario_name(scenario: str) -> str:
    names = {
        "own_damage": "Own Damage (Accident/Collision)",
        "theft": "Vehicle Theft",
        "third_party": "Third-Party Damage/Injury",
        "natural_calamity": "Natural Calamity",
        "hit_and_run": "Hit-and-Run",
        "denied_claim": "Claim Denial",
        "ncb": "No Claim Bonus (NCB)",
        "cashless_reimbursement": "Cashless vs Reimbursement",
        "surveyor_dispute": "Surveyor Assessment Dispute",
        "total_loss": "Total Loss / Write-Off",
    }
    return names.get(scenario, scenario or "General")


def generate_info_response(scenario: str, policy_type: Optional[str] = None, location: Optional[str] = None) -> str:
    relevant_cats = get_relevant_knowledge(scenario)
    kb = kb_load()
    response = f"{DISCLAIMER}\n\n## 📋 Your Claim Scenario: {get_scenario_name(scenario)}\n\n"
    
    scenario_texts = {
        "theft": "**Theft Claim Process:**\n1. **File FIR** — Within 24 hours at nearest police station\n2. **Notify Insurer** — Call helpline immediately (24/7)\n3. **Submit Documents** — FIR, claim form, RC, policy, driving license\n4. **Surveyor Inspection** — Insurer verifies the claim\n5. **Settlement** — Within 30 days after document submission\n\n**Key Tips:** File FIR within 24 hours. Keep all copies. Follow up regularly.",
        "own_damage": "**Own Damage Claim Process:**\n1. **Intimate Insurer** — Within 24-48 hours\n2. **File FIR** — If third-party involved\n3. **Surveyor Assessment** — Insurer inspects damage\n4. **Repair Estimate** — From approved workshop\n5. **Cashless/Reimbursement** — Based on garage choice\n6. **Settlement** — Direct to garage or reimbursement to you\n\n**Key Tips:** Choose IRDAI-approved workshop. Get approval before repairs for reimbursement claims.",
        "third_party": "**Third-Party Claim Process:**\n1. **File FIR** — **Mandatory** for injury/death claims\n2. **Intimate Insurer** — Within 24 hours\n3. **Claims Tribunal** — Third party files at MACT\n4. **Legal Proceedings** — Tribunal determines compensation\n5. **Settlement** — Based on tribunal award\n\n**Key Tips:** **FIR is mandatory**. Do not admit liability. Collect witness details. Consult a lawyer for injury claims.",
        "natural_calamity": "**Natural Calamity Claim Process:**\n1. **Document Damage** — Photos/videos of damage\n2. **Notify Insurer** — Within 24-48 hours\n3. **Surveyor Assessment** — Insurer evaluates damage\n4. **Submit Documents** — Photos, claim form, policy copy\n5. **Settlement** — For comprehensive policies (storm/flood/fire covered)\n\n**Key Tips:** Keep damage photos before repairs. Check policy exclusions.",
        "hit_and_run": "**Hit-and-Run Claim Process:**\n1. **File FIR Immediately** — **Mandatory**\n2. **Intimate Insurer** — Within 24 hours\n3. **Submit FIR Copy** — Primary evidence\n4. **Surveyor Assessment** — Insurer evaluates\n5. **Settlement** — Based on comprehensive coverage\n\n**Key Tips:** **FIR is absolutely mandatory**. Note any vehicle details. Own damage covered under comprehensive policy.",
        "denied_claim": "**Claim Denial Appeal Process:**\n1. **Get Denial Letter** — Request written reasons\n2. **Review Reasons** — Common: delayed intimation, expired policy, missing docs\n3. **Reply with Evidence** — Counter-evidence and documents\n4. **Appeal to Insurer** — Within 30 days\n5. **Escalate to SCORES** — If unresolved\n6. **Consumer Forum** — Last resort\n\n**Key Tips:** **SCORES portal** (scores.irdai.gov.in) is IRDAI's grievance system. IRDAI helpline: **1700-13-13-13**.",
        "ncb": "**No Claim Bonus (NCB) Information:**\n**Discounts by claim-free years:**\n- 1 year: 20% | 2 years: 25% | 3 years: 35%\n- 4 years: 45% | **5+ years: 50% maximum**\n\n**Key Points:**\n- NCB applies to **own-damage portion** only\n- Transferable between insurers\n- Lost if you make a claim (except exemptions)\n- Can be preserved for 2 years without a car\n\n**Tip:** For minor repairs, consider paying out-of-pocket to preserve NCB.",
        "cashless_reimbursement": "**Cashless vs. Reimbursement Claims:**\n\n**Cashless:** Repaired at network garage. Insurer pays directly. No upfront payment.\n\n**Reimbursement:** You pay first, claim later. More garage flexibility. Better for out-of-town.\n\n**Choose based on:** Network garage proximity vs. specialized repairs needed.",
        "surveyor_dispute": "**Surveyor Assessment Dispute Process:**\n1. **Get Assessment Report** — Request detailed report\n2. **Review Findings** — Compare with your estimate\n3. **Dispute in Writing** — Send formal dispute within 15 days\n4. **Submit Counter-Evidence** — Independent estimates, photos\n5. **Escalate** — Through insurer's grievance or SCORES\n\n**Tip:** Get multiple estimates. Document all damage with dated photos.",
        "total_loss": "**Total Loss (Write-Off) Claim Process:**\n1. **Assessment** — If repair > 75% of insured value = total loss\n2. **Settlement Options:** Full settlement vs. salvage retention\n3. **Depreciation** — Standard deductions apply (plastic 50%, rubber 50%, metal 0-20%)\n4. **Documents** — FIR, claim form, RC, policy copy\n5. **Settlement Receipt** — Review carefully before signing\n\n**Tip:** Understand depreciation before accepting. For <1 year old cars, depreciation is minimal.",
    }
    response += scenario_texts[scenario] + "\n\n"
    
    response += "\n---\n\n## 📚 Relevant Guidelines\n\n"
    for cat in relevant_cats:
        if cat in kb:
            response += f"### Source: {cat}\n\n"
            lines = kb[cat].split("\n")
            in_section = False
            section_lines = []
            for line in lines:
                if line.startswith("## "):
                    if in_section and section_lines:
                        response += "\n".join(section_lines[:20]) + "\n\n"
                        section_lines = []
                    in_section = True
                if in_section:
                    section_lines.append(line)
            if section_lines:
                response += "\n".join(section_lines[:20]) + "\n\n"
    
    response += get_action_items(scenario)
    return response


def get_action_items(scenario: str) -> str:
    items = {
        "theft": "**Immediate Action Items:**\n1. [ ] File FIR at nearest police station\n2. [ ] Call insurer helpline\n3. [ ] Gather: RC copy, insurance policy, driving license\n4. [ ] Submit to insurer\n5. [ ] Follow up for surveyor visit",
        "own_damage": "**Immediate Action Items:**\n1. [ ] Call insurer helpline within 24-48 hours\n2. [ ] If third-party involved, file FIR\n3. [ ] Get vehicle towed to authorized workshop\n4. [ ] Submit claim form and documents\n5. [ ] Track claim status regularly",
        "third_party": "**Immediate Action Items:**\n1. [ ] **File FIR** — mandatory\n2. [ ] Call insurer helpline\n3. [ ] Collect witness details and photos\n4. [ ] **Do NOT** admit liability at the scene\n5. [ ] Consult a lawyer for injury/death claims",
        "natural_calamity": "**Immediate Action Items:**\n1. [ ] Document damage with photos\n2. [ ] Notify insurer within 24 hours\n3. [ ] File FIR if applicable (flood claims)\n4. [ ] Prevent further damage\n5. [ ] Submit claim documents",
        "hit_and_run": "**Immediate Action Items:**\n1. [ ] **File FIR immediately** — mandatory\n2. [ ] Call insurer helpline within 24 hours\n3. [ ] Note any vehicle details\n4. [ ] Document damage with photos\n5. [ ] Submit all documents including FIR",
        "denied_claim": "**Immediate Action Items:**\n1. [ ] Request written denial letter\n2. [ ] Review denial reasons\n3. [ ] Gather counter-evidence\n4. [ ] File formal appeal with insurer\n5. [ ] If unresolved, file on SCORES portal",
        "ncb": "**NCB Tips:**\n1. [ ] For minor repairs, consider paying out-of-pocket\n2. [ ] Request NCB carry-forward letter when switching\n3. [ ] Maximum 50% discount on own-damage premium",
        "cashless_reimbursement": "**Decision Points:**\n1. [ ] Check if nearest garage is in network\n2. [ ] For cashless: get pre-approval\n3. [ ] For reimbursement: keep all invoices\n4. [ ] Compare time and cost of both options",
        "surveyor_dispute": "**Dispute Action Items:**\n1. [ ] Request detailed assessment report\n2. [ ] Get independent estimate\n3. [ ] Document damage with dated photos\n4. [ ] File written dispute with insurer\n5. [ ] Escalate on SCORES if unresolved",
        "total_loss": "**Total Loss Action Items:**\n1. [ ] Understand depreciation deductions\n2. [ ] Get multiple estimates if possible\n3. [ ] Decide: full settlement vs. salvage retention\n4. [ ] Review settlement breakdown carefully",
    }
    return items.get(scenario, "**Next Steps:**\n1. [ ] Gather required documents\n2. [ ] File claim through your insurer\n3. [ ] Track claim status regularly")


# ─── Conversation Engine (Open-Ended) ───

def process_message(message: str, state: str, scenario: Optional[str], policy: Optional[str], location: Optional[str]) -> dict:
    """Process a message and return the appropriate response."""
    clean_msg = strip_context(message)
    clean_lower = clean_msg.lower().strip()
    
    # Reset
    if any(kw in clean_lower for kw in ["start over", "new claim", "restart", "new conversation"]):
        return {
            "response": "🚗 **New conversation started.** Please describe your insurance situation or select a claim type from the sidebar.",
            "state": "greeting",
            "scenario": None,
            "policy_type": None,
            "location": None,
        }
    
    # === State: Greeting (first message or reset) ===
    if state == "greeting":
        # Always check general questions FIRST
        general_answer = answer_general_question(clean_msg)
        if general_answer:
            return {
                "response": general_answer,
                "state": "providing_info",
                "scenario": scenario,
                "policy_type": policy,
                "location": location,
            }
        
        # Check if this is a casual greeting/filler
        is_casual = bool(re.match(r'^(hi|hello|hey|howdy|greetings|good\s+(morning|afternoon|evening|night)|namaste|kya\s+haal|kaise\s+ho|sup|yo|hola|bonjour)\s*$', clean_lower))
        is_casual = is_casual or clean_lower in ['hi', 'hello', 'hey', 'hmm', 'ok', 'okay', 'yes', 'no', 'sure', 'cool', 'nice']
        is_casual = is_casual or len(clean_lower) <= 2
        
        if is_casual:
            return {
                "response": "👋 **Hello!** Welcome to ClaimRight.\n\nI'm here to help you navigate car insurance claims in India. I can guide you through:\n\n• **Own Damage** (accident/collision)\n• **Theft** claims\n• **Third-Party** damage/injury\n• **Natural Calamity** (flood, cyclone, earthquake)\n• **Hit-and-Run** claims\n• **Claim Denial** appeals\n• **NCB** (No Claim Bonus)\n• **Cashless vs Reimbursement**\n• **Surveyor disputes**\n• **Total Loss** settlements\n\n**What can I help you with today?** You can describe your situation or select a claim type from the sidebar.",
                "state": "greeting",
                "scenario": None,
                "policy_type": None,
                "location": None,
            }
        
        # Detect scenario
        detected = detect_scenario_from_text(clean_msg)
        
        # User specified a scenario
        scenario = detected
        return {
            "response": f"I understand your **{get_scenario_name(scenario).lower()}** case. Let me help you through the claim process.\n\nTo provide accurate guidance, I need a bit more info:\n\n1. **Policy type?** (Comprehensive / Third-Party Only)\n2. **Location?** (City/State)\n\nYou can type them together: 'Comprehensive, Mumbai'",
            "state": "collecting_policy",
            "scenario": scenario,
            "policy_type": None,
            "location": None,
        }
    
    # === State: Collecting Policy Info ===
    if state == "collecting_policy":
        new_policy = detect_policy(clean_msg, policy)
        new_location = detect_location(clean_msg, location)
        
        policy_ok = new_policy and len(new_policy) > 3
        location_ok = new_location and len(new_location) > 2
        
        if policy_ok:
            policy = new_policy
        if location_ok:
            location = new_location
        
        if policy_ok and location_ok:
            info = generate_info_response(scenario, policy, location)
            return {
                "response": info,
                "state": "providing_info",
                "scenario": scenario,
                "policy_type": policy,
                "location": location,
            }
        
        needed = []
        if not policy_ok:
            needed.append("**Policy type** (Comprehensive / Third-Party Only)")
        if not location_ok:
            needed.append("**Location** (City/State)")
        
        return {
            "response": f"I still need:\n- {', '.join(needed)}\n\nYou can type: 'Comprehensive, Mumbai'",
            "state": "collecting_policy",
            "scenario": scenario,
            "policy_type": policy,
            "location": location,
        }
    
    # === State: Providing Info (follow-ups) ===
    if state == "providing_info":
        # Summary
        if "summary" in clean_lower:
            summary = generate_claim_summary(scenario, policy, location)
            return {
                "response": f"## 📄 Your Claim Summary:\n\n{summary}",
                "state": "providing_info",
                "scenario": scenario,
                "policy_type": policy,
                "location": location,
                "has_summary": True,
            }
        
        # Escalation
        if "escalat" in clean_lower:
            return {
                "response": f"## 🔥 Escalation Process for {get_scenario_name(scenario)}\n\n**Step 1: Internal Grievance**\n1. Contact insurer's grievance officer\n2. File written complaint within 30 days\n3. Response within 15 days\n\n**Step 2: IRDAI SCORES Portal**\n1. Visit scores.irdai.gov.in\n2. Register with PAN and policy details\n3. File complaint\n4. Resolution within 30 days\n\n**Step 3: Consumer Forum**\n1. District Commission (up to ₹20 Lakhs)\n2. State/National Commission (above ₹20 Lakhs)\n\n**IRDAI Helpline:** 1700-13-13-13",
                "state": "providing_info",
                "scenario": scenario,
                "policy_type": policy,
                "location": location,
            }
        
        # If user is asking a different scenario, let them switch
        new_scenario = detect_scenario_from_text(clean_msg)
        if new_scenario and new_scenario != scenario:
            return {
                "response": f"I can help with **{get_scenario_name(new_scenario)}** as well. Let me provide guidance for that.\n\nPlease provide:\n1. **Policy type?** (Comprehensive / Third-Party Only)\n2. **Location?** (City/State)",
                "state": "collecting_policy",
                "scenario": new_scenario,
                "policy_type": None,
                "location": None,
            }
        
        # General follow-up
        info = generate_info_response(scenario, policy, location)
        return {
            "response": info,
            "state": "providing_info",
            "scenario": scenario,
            "policy_type": policy,
            "location": location,
        }
    
    # Default
    return {
        "response": "Please select a claim type from the sidebar or describe your situation.",
        "state": "greeting",
        "scenario": scenario,
        "policy_type": policy,
        "location": location,
    }


def answer_general_question(text: str) -> Optional[str]:
    """Answer general questions without needing a scenario."""
    lower = text.lower()
    
    if "how does claim work" in lower or "claim process" in lower or "how does car insurance" in lower or "car insurance claim work" in lower or "how to file a car insurance" in lower or "how to file a claim" in lower:
        return "**How Car Insurance Claims Work in India:**\n\n1. **Intimate Insurer** — Call within 24-48 hours of incident\n2. **File FIR** — Required for theft, third-party injury, fire, etc.\n3. **Surveyor Assessment** — Insurer sends surveyor to evaluate damage\n4. **Submit Documents** — Claim form, FIR, RC, policy, driving license\n5. **Repair** — Cashless (network garage) or Reimbursement (your garage)\n6. **Settlement** — IRDAI mandates settlement within 30 days of document submission\n\n**For specific guidance, please describe your situation or select a claim type from the sidebar.**"
    
    if "ncb" in lower or "no claim bonus" in lower:
        return "**No Claim Bonus (NCB):**\n\nNCB is a discount on your own-damage premium for each claim-free year:\n\n• 1 year: **20%** | 2 years: **25%** | 3 years: **35%**\n• 4 years: **45%** | **5+ years: 50% maximum**\n\n**Key points:**\n• Applies to own-damage portion only\n• Transferable between insurers\n• Lost if you make a claim (except exemptions)\n• Can be preserved for 2 years without owning a car"
    
    if "score" in lower or "complain" in lower or "grievance" in lower:
        return "**Filing a Complaint:**\n\n**IRDAI SCORES Portal** — scores.irdai.gov.in\n**IRDAI Helpline:** 1700-13-13-13\n**Email:** complaints@irdai.gov.in\n\n**Steps:**\n1. Register on SCORES with your PAN\n2. File complaint against insurer\n3. IRDAI mandates resolution within 30 days\n4. If unresolved, approach Consumer Forum"
    
    if "cashless" in lower:
        return "**Cashless vs Reimbursement:**\n\n**Cashless:**\n• Vehicle repaired at insurer's network garage\n• Insurer pays garage directly\n• No upfront payment\n\n**Reimbursement:**\n• You pay first, claim later\n• More garage flexibility\n• Better for out-of-town claims\n\n**Choose cashless if:** a network garage is nearby. **Choose reimbursement if:** you need a specialized garage or are out of town."
    
    if "what is" in lower and ("third" in lower or "tp" in lower):
        return "**Third-Party Insurance:**\n\nMandatory by law in India. Covers:\n• **Third-party property damage**\n• **Third-party bodily injury/death**\n• **Legal liabilities**\n\n**Does NOT cover:** Your own vehicle's damage.\n\nFor own-damage coverage, you need **Comprehensive Insurance** (adds own-damage + third-party + optional add-ons)."
    
    return None


def generate_claim_summary(scenario, policy=None, location=None):
    from datetime import datetime
    return (
        f"# 📄 Claim Summary - {get_scenario_name(scenario)}\n\n"
        f"**Policy:** {policy or 'Not specified'} | **Location:** {location or 'Not specified'}\n"
        f"**Date:** {datetime.now().strftime('%Y-%m-%d')}\n\n"
        "**Required Documents:**\n"
        "- Insurance policy copy\n- RC copy\n- Driving license\n- FIR (if applicable)\n- Claim form\n- Repair estimates\n\n"
        f"**Process:** Follow the steps for {get_scenario_name(scenario).lower()}."
    )


# ─── API Endpoints ───

@app.get("/", response_class=HTMLResponse)
def root():
    return HTMLResponse(content=UI_HTML)


@app.get("/health")
def health():
    return {"status": "healthy", "service": "ClaimRight", "version": "0.1.0"}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    try:
        result = process_message(req.message, req.state, req.scenario, req.policy_type, req.location)
        return ChatResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/app", response_class=HTMLResponse)
def serve_ui():
    return HTMLResponse(content=UI_HTML)


UI_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ClaimRight — Car Insurance Claim Guide for India</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f7f8fa; color: #1a1a2e; }
  .header { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); color: white; padding: 24px; text-align: center; }
  .header h1 { font-size: 1.8em; }
  .header p { opacity: 0.8; margin-top: 4px; }
  .disclaimer { background: #fff3cd; border-left: 4px solid #ffc107; padding: 12px 16px; margin: 12px 20px; border-radius: 4px; font-size: 0.85em; }
  .disclaimer strong { color: #856404; }
  .sidebar { position: fixed; left: 0; top: 0; bottom: 0; width: 260px; background: #1a1a2e; color: #ccc; padding: 20px; overflow-y: auto; z-index: 10; }
  .sidebar h3 { color: #fff; margin: 16px 0 8px; font-size: 0.9em; text-transform: uppercase; letter-spacing: 1px; }
  .sidebar label { display: block; font-size: 0.85em; margin-bottom: 4px; color: #aaa; }
  .sidebar select, .sidebar input { width: 100%; padding: 8px; margin-bottom: 12px; background: #16213e; border: 1px solid #333; color: #eee; border-radius: 6px; font-size: 0.9em; }
  .sidebar button { width: 100%; padding: 10px; margin: 6px 0; border: none; border-radius: 6px; cursor: pointer; font-size: 0.9em; }
  .btn-primary { background: #0f3460; color: white; }
  .btn-primary:hover { background: #1a5276; }
  .btn-secondary { background: #333; color: #ccc; }
  .btn-secondary:hover { background: #444; }
  .chat-area { margin-left: 260px; display: flex; flex-direction: column; height: 100vh; }
  .chat-area .header { margin-left: -260px; }
  #messages { flex: 1; overflow-y: auto; padding: 20px; }
  .msg { max-width: 75%; margin-bottom: 12px; padding: 12px 16px; border-radius: 16px; font-size: 0.95em; line-height: 1.5; white-space: pre-wrap; word-wrap: break-word; }
  .msg.user { background: #0f3460; color: white; margin-left: auto; border-bottom-right-radius: 4px; }
  .msg.assistant { background: white; border: 1px solid #e0e0e0; margin-right: auto; border-bottom-left-radius: 4px; }
  .input-area { padding: 16px 20px; background: white; border-top: 1px solid #e0e0e0; display: flex; gap: 8px; }
  #input { flex: 1; padding: 12px 16px; border: 1px solid #ddd; border-radius: 24px; font-size: 1em; outline: none; }
  #input:focus { border-color: #0f3460; }
  #send { padding: 12px 24px; background: #0f3460; color: white; border: none; border-radius: 24px; cursor: pointer; font-size: 1em; font-weight: 600; }
  #send:hover { background: #1a5276; }
  #send:disabled { background: #999; cursor: not-allowed; }
  .loading { color: #999; font-style: italic; font-size: 0.85em; padding: 8px 20px; }
  .about { margin-top: 20px; font-size: 0.8em; line-height: 1.6; }
  .about a { color: #4fc3f7; text-decoration: none; }
  .health { margin-top: 16px; font-size: 0.85em; }
  .health .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
  .health .dot.green { background: #2ecc71; }
  .health .dot.red { background: #e74c3c; }
  .quick-actions { margin-top: 16px; font-size: 0.8em; }
  .quick-actions button { width: 100%; padding: 6px 10px; margin: 4px 0; border: 1px solid #444; border-radius: 6px; cursor: pointer; font-size: 0.85em; background: #16213e; color: #ccc; text-align: left; }
  .quick-actions button:hover { background: #1a5276; color: white; }
  @media (max-width: 768px) {
    .sidebar { display: none; }
    .chat-area { margin-left: 0; }
    .msg { max-width: 90%; }
  }
</style>
</head>
<body>

<div class="sidebar">
  <h1 style="color:white;font-size:1.3em;">🚗 ClaimRight</h1>
  <p style="font-size:0.8em;opacity:0.7;margin-bottom:20px;">Car Insurance Claim Guide for India</p>

  <h3>📋 Claim Type</h3>
  <label>What happened?</label>
  <select id="scenario" onchange="onScenarioChange()">
    <option value="">— Select —</option>
    <option value="own_damage">Own Damage (Accident/Collision)</option>
    <option value="theft">Vehicle Theft</option>
    <option value="third_party">Third-Party Damage/Injury</option>
    <option value="natural_calamity">Natural Calamity</option>
    <option value="hit_and_run">Hit-and-Run</option>
    <option value="denied_claim">Claim Denial / Appeal</option>
    <option value="ncb">No Claim Bonus (NCB)</option>
    <option value="cashless_reimbursement">Cashless vs Reimbursement</option>
    <option value="surveyor_dispute">Surveyor Assessment Dispute</option>
    <option value="total_loss">Total Loss / Write-Off</option>
  </select>

  <h3>📄 Policy Info</h3>
  <label>Policy Type</label>
  <select id="policy_type" onchange="onPolicyTypeChange()">
    <option value="">— Select —</option>
    <option value="Comprehensive">Comprehensive</option>
    <option value="Third-Party Only">Third-Party Only</option>
  </select>
  <label>Location (City/State)</label>
  <input id="location" placeholder="e.g., Mumbai, Maharashtra" />

  <h3>⚙️ Actions</h3>
  <button class="btn-secondary" onclick="resetChat()">🔄 New Conversation</button>
  <button class="btn-primary" onclick="generateSummary()">📄 Claim Summary</button>

  <h3>💡 Quick Help</h3>
  <div class="quick-actions">
    <button onclick="quickAsk('How does car insurance claim work?')">📖 How claims work</button>
    <button onclick="quickAsk('What is NCB?')">🎁 What is NCB?</button>
    <button onclick="quickAsk('How to file a complaint?')">😡 File a complaint</button>
    <button onclick="quickAsk('What is third party insurance?')">🤝 Third-party insurance</button>
  </div>

  <div class="about">
    <h3>ℹ️ About</h3>
    <p><strong>ClaimRight v0.2.0</strong></p>
    <p>Guidance bot for IRDAI-regulated car insurance claims in India.</p>
    <p style="margin-top:8px;"><a href="https://irdai.gov.in" target="_blank">IRDAI Official</a><br>
    <a href="https://scores.irdai.gov.in" target="_blank">SCORES Portal</a><br>
    📞 IRDAI Helpline: 1700-13-13-13</p>
  </div>

  <div class="health" id="health_status">
    <span class="dot red"></span> Checking...
  </div>
</div>

<div class="chat-area">
  <div class="header">
    <h1>🚗 ClaimRight</h1>
    <p>Your Car Insurance Claim Guide for India</p>
  </div>
  <div class="disclaimer">
    <strong>⚠️ Disclaimer:</strong> General information only. Not legal advice. For specific guidance, consult a qualified insurance lawyer or your insurer.
  </div>
  <div id="messages"></div>
  <div class="loading" id="loading" style="display:none;">ClaimRight is analyzing your claim...</div>
  <div class="input-area">
    <input id="input" placeholder="Describe your insurance situation..." onkeydown="if(event.key==='Enter'){event.preventDefault();sendMessage()}" />
    <button id="send" type="button" onclick="sendMessage()">Send</button>
  </div>
</div>

<script>
const API = '';
let state = 'greeting';
let scenario = null;
let policyType = null;
let locationVal = null;

function mdToHtml(md) {
  if (!md) return '';
  let html = md
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/## (.+)/g, '<h3 style="margin:10px 0 6px;color:#1a1a2e;">$1</h3>')
    .replace(/### (.+)/g, '<h4 style="margin:8px 0 4px;color:#333;">$1</h4>')
    .replace(/^• (.+)$/gm, '<span style="display:block;margin-left:16px;">• $1</span>')
    .replace(/^(\d+)\. (.+)$/gm, '<span style="display:block;margin-left:16px;">$1. $2</span>')
    .replace(/^- (.+)$/gm, '<span style="display:block;margin-left:24px;">• $1</span>')
    .replace(/^---$/gm, '<hr style="border:none;border-top:1px solid #e0e0e0;margin:14px 0;">')
    .replace(/\n/g, '<br>');
  return html;
}

function addMessage(role, text) {
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.innerHTML = role === 'assistant' ? mdToHtml(text) : text.replace(/\n/g, '<br>');
  document.getElementById('messages').appendChild(div);
  document.getElementById('messages').scrollTop = document.getElementById('messages').scrollHeight;
}

function getSidebarScenario() {
  const val = document.getElementById('scenario').value;
  return val || null;
}

async function sendMessage() {
  const input = document.getElementById('input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  
  addMessage('user', text);
  document.getElementById('loading').style.display = 'block';
  document.getElementById('send').disabled = true;

  try {
    const resp = await fetch(API + '/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        message: text,
        state: state,
        scenario: scenario,
        policy_type: policyType,
        location: locationVal,
      })
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    addMessage('assistant', data.response);
    
    state = data.state;
    if (data.scenario) scenario = data.scenario;
    if (data.policy_type) policyType = data.policy_type;
    if (data.location) locationVal = data.location;
  } catch (err) {
    addMessage('assistant', `⚠️ Error: ${err.message}`);
  } finally {
    document.getElementById('loading').style.display = 'none';
    document.getElementById('send').disabled = false;
  }
}

function quickAsk(question) {
  document.getElementById('input').value = question;
  quickSendMessage();
}

async function quickSendMessage() {
  await sendMessage();
}

function onScenarioChange() {
  const val = document.getElementById('scenario').value;
  if (val) {
    scenario = val;
    policyType = null;
    locationVal = null;
    state = 'collecting_policy';
    document.getElementById('policy_type').value = '';
    document.getElementById('location').value = '';
    // Send the selected scenario as a message
    document.getElementById('input').value = '';
    quickSendMessage();
  }
}

function onPolicyTypeChange() {
  // Just update the local state; it's sent along with the next sendMessage
}

async function resetChat() {
  state = 'greeting';
  scenario = null;
  policyType = null;
  locationVal = null;
  
  document.getElementById('messages').innerHTML = '';
  
  addMessage('assistant', "🚗 **New conversation started.** Please describe your insurance situation or select a claim type from the sidebar.");
}

async function generateSummary() {
  const scen = scenario || getSidebarScenario();
  const pol = policyType || document.getElementById('policy_type').value;
  const loc = locationVal || document.getElementById('location').value;
  
  if (!scen) {
    addMessage('assistant', '⚠️ Please select a claim type first.');
    return;
  }
  
  try {
    const resp = await fetch(API + '/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        message: 'Generate a summary of my claim',
        state: state,
        scenario: scen,
        policy_type: pol,
        location: loc,
      })
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    addMessage('assistant', data.response);
  } catch (err) {
    addMessage('assistant', `⚠️ Summary error: ${err.message}`);
  }
}

async function checkHealth() {
  const el = document.getElementById('health_status');
  try {
    const r = await fetch(API + '/health');
    if (r.ok) {
      el.innerHTML = '<span class="dot green"></span> Backend Connected';
    } else {
      el.innerHTML = '<span class="dot red"></span> Backend Unhealthy';
    }
  } catch {
    el.innerHTML = '<span class="dot red"></span> Backend Offline';
  }
}

checkHealth();
</script>
</body>
</html>
"""


# Vercel serverless adapter
def handler(event, context):
    from fastapi.responses import JSONResponse, Response

    if event["httpMethod"] == "GET" and event["path"] in ["/", "/app"]:
        return Response(content=UI_HTML, media_type="text/html", status_code=200)

    if event.get("path") == "/health" and event["httpMethod"] == "GET":
        return JSONResponse(content={"status": "healthy", "service": "ClaimRight"}, status_code=200)

    return JSONResponse(content={"error": "not found"}, status_code=404)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
