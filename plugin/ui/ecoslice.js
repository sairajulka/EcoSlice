// ============================================================
// ECOSLICE UI
// ============================================================


let selectedOption = "balanced";


// ============================================================
// ORCASLICER MESSAGE HELPER
// ============================================================

function post(type, payload = {}) {

    window.orca.postMessage({

        type: type,

        ...payload

    });

}


// ============================================================
// ANALYZE
// ============================================================

function analyze() {

    const intent =
        document
            .getElementById("intent")
            .value
            .trim();


    const status =
        document.getElementById(
            "status"
        );


    status.innerText =
        "Analyzing current OrcaSlicer model...";


    post(
        "analyze",
        {
            intent: intent
        }
    );

}


// ============================================================
// SELECT OPTION
// ============================================================

function selectOption(option) {

    selectedOption = option;


    document
        .querySelectorAll(
            ".option"
        )
        .forEach(card => {

            card.classList.remove(
                "selected"
            );

        });


    const card =
        document.querySelector(
            `[data-option="${option}"]`
        );


    if (card) {

        card.classList.add(
            "selected"
        );

    }


    post(
        "select_option",
        {
            option: option
        }
    );

}


// ============================================================
// RENDER RESULTS
// ============================================================

function render(result) {

    document
        .getElementById("results")
        .classList
        .remove("hidden");


    document
        .getElementById("status")
        .innerText =
            "Analysis complete.";


    // --------------------------------------------------------
    // Geometry
    // --------------------------------------------------------

    document
        .getElementById("volume")
        .innerText =
            Math.round(
                result.geometry.volume_mm3
            ).toLocaleString();


    document
        .getElementById("triangles")
        .innerText =
            result.geometry.triangles
                .toLocaleString();


    document
        .getElementById("risk")
        .innerText =
            result.geometry.support_risk
                .toFixed(1) + "%";


    // --------------------------------------------------------
    // Intent
    // --------------------------------------------------------

    document
        .getElementById("priority")
        .innerText =
            result.intent.priority;


    document
        .getElementById("load")
        .innerText =

        result.intent.load_kg === null

            ? "Not specified"

            : result.intent.load_kg
                + " kg";


    document
        .getElementById("outdoor")
        .innerText =

        result.intent.outdoor
            ? "Yes"
            : "No";


    document
        .getElementById("vibration")
        .innerText =

        result.intent.vibration
            ? "Yes"
            : "No";


    // --------------------------------------------------------
    // Warnings
    // --------------------------------------------------------

    const warnings =
        document.getElementById(
            "warnings"
        );


    warnings.innerHTML = "";


    if (
        result.geometry.support_risk > 50
    ) {

        warnings.innerHTML += `

            <div class="warning">

                ⚠️ High support risk detected.
                EcoSlice recommends evaluating
                orientation before generating supports.

            </div>

        `;

    }


    if (
        result.geometry
            .thin_feature_warning
    ) {

        warnings.innerHTML += `

            <div class="warning">

                ⚠️ Thin geometry detected.
                EcoSlice may increase wall thickness
                in critical regions.

            </div>

        `;

    }


    // --------------------------------------------------------
    // Optimization cards
    // --------------------------------------------------------

    const container =
        document.getElementById(
            "options"
        );


    container.innerHTML = "";


    result.options.forEach(
        option => {

            const card =
                document.createElement(
                    "div"
                );


            card.className =
                "option";


            if (
                option.id === "balanced"
            ) {

                card.classList.add(
                    "recommended"
                );

            }


            card.dataset.option =
                option.id;


            card.innerHTML = `

                ${
                    option.id === "balanced"

                    ? `
                        <div class="recommended-label">
                            RECOMMENDED
                        </div>
                    `

                    : ""
                }


                <div class="option-name">

                    ${option.name}

                </div>


                <div class="option-description">

                    ${option.description}

                </div>


                <div class="option-stat">

                    <span>Walls</span>

                    <strong>
                        ${option.walls}
                    </strong>

                </div>


                <div class="option-stat">

                    <span>Infill</span>

                    <strong>
                        ${option.infill}%
                    </strong>

                </div>


                <div class="option-divider"></div>


                <div class="big-stat">

                    ${option.material_g.toFixed(1)} g

                </div>


                <div class="small-stat">

                    ${option.time_hours.toFixed(2)} h

                </div>


                <div class="small-stat">

                    ${option.energy_kwh.toFixed(2)} kWh

                </div>


                <div class="small-stat">

                    ${option.co2e_kg.toFixed(2)} kg CO₂e

                </div>


                <div class="confidence">

                    <span>
                        Strength confidence
                    </span>

                    <strong>

                        ${option.strength_confidence.toFixed(0)}%

                    </strong>

                </div>


                <button
                    class="select-button ${
                        option.id === "balanced"
                            ? "primary"
                            : ""
                    }"
                >

                    Select

                </button>

            `;


            card.addEventListener(
                "click",
                () => {

                    selectOption(
                        option.id
                    );

                }
            );


            const button =
                card.querySelector(
                    ".select-button"
                );


            button.addEventListener(
                "click",
                event => {

                    event.stopPropagation();

                    selectOption(
                        option.id
                    );

                }
            );


            container.appendChild(
                card
            );

        }
    );


    // --------------------------------------------------------
    // Explanation
    // --------------------------------------------------------

    const explanation =
        document.getElementById(
            "explanation"
        );


    explanation.innerHTML = "";


    result.explanation.forEach(
        text => {

            explanation.innerHTML += `

                <div class="change">

                    <span class="change-symbol">
                        +
                    </span>

                    <div>

                        <strong>
                            EcoSlice recommendation
                        </strong>

                        <p>
                            ${text}
                        </p>

                    </div>

                </div>

            `;

        }
    );


    selectOption(
        "balanced"
    );

}


// ============================================================
// MESSAGE FROM PYTHON
// ============================================================

function receive(data) {

    if (
        data.type === "result"
    ) {

        render(
            data.result
        );

    }


    else if (
        data.type === "error"
    ) {

        document
            .getElementById(
                "status"
            )
            .innerText =
                "Error: " +
                data.message;

    }


    else if (
        data.type === "status"
    ) {

        document
            .getElementById(
                "status"
            )
            .innerText =
                data.message;

    }

}


// ============================================================
// BUTTONS
// ============================================================

document
    .getElementById(
        "analyze"
    )
    .addEventListener(
        "click",
        analyze
    );


document
    .getElementById(
        "optimize"
    )
    .addEventListener(
        "click",
        () => {

            post(
                "optimize",
                {
                    option:
                        selectedOption
                }
            );

        }
    );


// ============================================================
// ORCASLICER → JAVASCRIPT
// ============================================================

window.orca.onMessage(
    receive
);