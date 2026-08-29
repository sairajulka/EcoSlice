/* ============================================================
   ECOSLICE v0.2.0
   OrcaSlicer Plugin UI
   ============================================================ */


/* ============================================================
   GLOBAL STATE
   ============================================================ */

let DATA = null;

let MODE = "solid";

let SELECTED_PROFILE = "balanced";

let rotationX = -0.45;
let rotationY = 0.65;

let zoom = 1;

let dragging = false;

let lastMouseX = 0;
let lastMouseY = 0;


/* ============================================================
   DOM HELPERS
   ============================================================ */

function el(id) {
    return document.getElementById(id);
}


function setText(id, value) {

    const element = el(id);

    if (element) {
        element.textContent = value;
    }

}


/* ============================================================
   INITIALIZATION
   ============================================================ */

document.addEventListener(
    "DOMContentLoaded",
    function () {

        setupCanvas();

        setupKeyboard();

        draw();

    }
);


/* ============================================================
   CANVAS SETUP
   ============================================================ */

let canvas = null;
let ctx = null;


function setupCanvas() {

    canvas = el("canvas");

    if (!canvas) {
        console.error("EcoSlice: canvas not found.");
        return;
    }

    ctx = canvas.getContext("2d");

    resizeCanvas();

    window.addEventListener(
        "resize",
        resizeCanvas
    );


    /* -------------------------
       Mouse rotation
       ------------------------- */

    canvas.addEventListener(
        "mousedown",
        function (event) {

            dragging = true;

            lastMouseX = event.clientX;
            lastMouseY = event.clientY;

            canvas.style.cursor = "grabbing";

        }
    );


    window.addEventListener(
        "mouseup",
        function () {

            dragging = false;

            if (canvas) {
                canvas.style.cursor = "grab";
            }

        }
    );


    window.addEventListener(
        "mousemove",
        function (event) {

            if (!dragging) {
                return;
            }

            const dx =
                event.clientX - lastMouseX;

            const dy =
                event.clientY - lastMouseY;


            rotationY += dx * 0.01;

            rotationX += dy * 0.01;


            lastMouseX =
                event.clientX;

            lastMouseY =
                event.clientY;


            draw();

        }
    );


    /* -------------------------
       Scroll zoom
       ------------------------- */

    canvas.addEventListener(
        "wheel",
        function (event) {

            event.preventDefault();

            if (event.deltaY > 0) {
                zoom *= 0.9;
            } else {
                zoom *= 1.1;
            }


            zoom =
                Math.max(
                    0.4,
                    Math.min(
                        4,
                        zoom
                    )
                );


            draw();

        },
        {
            passive: false
        }
    );

}


function resizeCanvas() {

    if (!canvas || !ctx) {
        return;
    }


    const rect =
        canvas.getBoundingClientRect();


    const dpr =
        window.devicePixelRatio || 1;


    canvas.width =
        Math.max(
            1,
            Math.floor(
                rect.width * dpr
            )
        );


    canvas.height =
        Math.max(
            1,
            Math.floor(
                rect.height * dpr
            )
        );


    ctx.setTransform(
        dpr,
        0,
        0,
        dpr,
        0,
        0
    );


    draw();

}


/* ============================================================
   KEYBOARD CONTROLS
   ============================================================ */

function setupKeyboard() {

    document.addEventListener(
        "keydown",
        function (event) {

            if (
                event.key === "r" ||
                event.key === "R"
            ) {

                rotationX = -0.45;
                rotationY = 0.65;
                zoom = 1;

                draw();

            }

        }
    );

}


/* ============================================================
   VIEW MODES
   ============================================================ */

function setMode(mode) {

    MODE = mode;


    document
        .querySelectorAll(".mode")
        .forEach(
            function (button) {

                button.classList.remove(
                    "active"
                );

            }
        );


    if (mode === "solid") {

        el("solidMode")?.classList.add(
            "active"
        );

    }

    if (mode === "stress") {

        el("stressMode")?.classList.add(
            "active"
        );

    }

    if (mode === "supports") {

        el("supportsMode")?.classList.add(
            "active"
        );

    }


    draw();

}


/* ============================================================
   NAVIGATION
   ============================================================ */

function setSection(section) {

    document
        .querySelectorAll(".nav-item")
        .forEach(
            function (item) {

                item.classList.remove(
                    "active"
                );

            }
        );


    const items =
        document.querySelectorAll(
            ".nav-item"
        );


    if (section === "workspace") {

        items[0]?.classList.add(
            "active"
        );

    }

    if (section === "analysis") {

        items[1]?.classList.add(
            "active"
        );

        document
            .querySelector(".right")
            ?.scrollIntoView({
                behavior: "smooth"
            });

    }

    if (section === "compare") {

        items[2]?.classList.add(
            "active"
        );

        showNotification(
            "Compare mode is ready after an optimization profile is selected."
        );

    }

    if (section === "validation") {

        items[3]?.classList.add(
            "active"
        );

        showNotification(
            "Validation will compare the optimized configuration against the current model."
        );

    }

}


/* ============================================================
   INTENT EXAMPLES
   ============================================================ */

function setIntent(text) {

    const textarea =
        el("intent");

    if (!textarea) {
        return;
    }


    textarea.value = text;

    textarea.focus();

}


/* ============================================================
   ANALYSIS
   ============================================================ */

function analyze() {

    const textarea =
        el("intent");


    const intent =
        textarea
            ? textarea.value.trim()
            : "";


    setStatus(
        "Analyzing current OrcaSlicer model...",
        "loading"
    );


    const message = {

        type: "analyze",

        intent: intent

    };


    /* ---------------------------------------------
       Real OrcaSlicer plugin bridge
       --------------------------------------------- */

    if (
        window.orca &&
        typeof window.orca.postMessage === "function"
    ) {

        try {

            window.orca.postMessage(
                message
            );

            return;

        } catch (error) {

            console.error(
                "EcoSlice Orca bridge error:",
                error
            );

        }

    }


    /* ---------------------------------------------
       Browser fallback
       --------------------------------------------- */

    /*
       This lets you test the UI in a normal browser
       even when OrcaSlicer is not hosting the plugin.
    */

    setStatus(
        "OrcaSlicer bridge unavailable. Using demo analysis.",
        "warning"
    );


    setTimeout(
        function () {

            updateUI(
                createDemoData()
            );

        },
        500
    );

}


/* ============================================================
   STATUS
   ============================================================ */

function setStatus(
    message,
    type = ""
) {

    const status =
        el("status");


    if (!status) {
        return;
    }


    status.textContent =
        message;


    status.className =
        "status-message";


    if (type) {

        status.classList.add(
            type
        );

    }

}


/* ============================================================
   ORCA MESSAGE BRIDGE
   ============================================================ */

function setupOrcaBridge() {

    if (
        window.orca &&
        typeof window.orca.onMessage === "function"
    ) {

        window.orca.onMessage(
            function (data) {

                console.log(
                    "EcoSlice received:",
                    data
                );


                if (
                    data.type === "analysis"
                ) {

                    setStatus(
                        "Analysis complete.",
                        "success"
                    );


                    updateUI(
                        data.data
                    );

                }


                if (
                    data.type === "error"
                ) {

                    setStatus(
                        "Error: " +
                        (
                            data.message ||
                            "Unknown error"
                        ),
                        "error"
                    );

                }

            }
        );

    }

}


/* ============================================================
   RUN BRIDGE SETUP
   ============================================================ */

setupOrcaBridge();


/* ============================================================
   UPDATE ENTIRE UI
   ============================================================ */

function updateUI(data) {

    if (!data) {
        return;
    }


    DATA = data;


    const geometry =
        data.geometry || {};


    const analysis =
        data.analysis || {};


    /* -------------------------
       Model name
       ------------------------- */

    setText(
        "modelName",
        data.objects?.[0]?.name ||
        "Current OrcaSlicer Model"
    );


    setText(
        "modelSub",
        "EcoSlice analysis complete"
    );


    /* -------------------------
       Dimensions
       ------------------------- */

    if (
        Array.isArray(
            geometry.dimensions_mm
        )
    ) {

        setText(
            "dimensions",
            geometry.dimensions_mm
                .map(
                    function (x) {

                        return Number(x)
                            .toFixed(1);

                    }
                )
                .join(" × ")
                + " mm"
        );

    }


    /* -------------------------
       Volume
       ------------------------- */

    if (
        geometry.volume_mm3 !== undefined
    ) {

        setText(
            "volume",
            Number(
                geometry.volume_mm3
            ).toLocaleString()
            + " mm³"
        );

    }


    /* -------------------------
       Triangles
       ------------------------- */

    if (
        geometry.triangles !== undefined
    ) {

        setText(
            "triangles",
            Number(
                geometry.triangles
            ).toLocaleString()
        );

    }


    /* -------------------------
       Support risk
       ------------------------- */

    if (
        geometry.support_risk !== undefined
    ) {

        setText(
            "supportRisk",
            Number(
                geometry.support_risk
            ).toFixed(1)
            + "%"
        );

    }


    /* -------------------------
       Overhang
       ------------------------- */

    if (
        analysis.overhang_faces !== undefined
    ) {

        setText(
            "overhang",
            Number(
                analysis.overhang_faces
            ).toLocaleString()
            + " faces"
        );

    }


    /* -------------------------
       Stress
       ------------------------- */

    if (
        analysis.stress_max !== undefined
    ) {

        setText(
            "stress",
            Math.round(
                Number(
                    analysis.stress_max
                ) * 100
            )
            + "% max"
        );

    }


    /* -------------------------
       Support count
       ------------------------- */

    if (
        analysis.support_points !== undefined
    ) {

        setText(
            "supportCount",
            Number(
                analysis.support_points
            ).toLocaleString()
            + " regions"
        );

    }


    /* -------------------------
       Watertight
       ------------------------- */

    if (
        geometry.manifold !== undefined
    ) {

        setText(
            "watertight",
            geometry.manifold
                ? "YES"
                : "NO"
        );

    }


    /* -------------------------
       Profiles
       ------------------------- */

    renderProfiles(
        data.profiles || []
    );


    /* -------------------------
       Changes
       ------------------------- */

    renderChanges(
        data.changes || []
    );


    /* -------------------------
       Draw model
       ------------------------- */

    draw();

}


/* ============================================================
   OPTIMIZATION PROFILES
   ============================================================ */

function renderProfiles(profiles) {

    const container =
        el("profiles");


    if (!container) {
        return;
    }


    container.innerHTML = "";


    if (!profiles.length) {

        container.innerHTML = `
            <div class="empty-state">
                No optimization profiles were returned.
            </div>
        `;

        return;

    }


    profiles.forEach(
        function (profile) {

            const card =
                document.createElement(
                    "div"
                );


            const recommended =
                profile.id === "balanced";


            card.className =
                "profile" +
                (
                    recommended
                        ? " recommended"
                        : ""
                );


            const description =
                profile.id === "eco"
                    ? "Minimize material and print time."
                    : profile.id === "balanced"
                        ? "Balance strength, material, and time."
                        : "Prioritize structural robustness.";


            card.innerHTML = `

                <div class="profile-top">

                    <div>

                        <div class="profile-name">
                            ${escapeHTML(profile.name || profile.id)}
                        </div>

                        <div class="profile-description">
                            ${description}
                        </div>

                    </div>

                    ${
                        recommended
                            ? `<div class="profile-tag">
                                RECOMMENDED
                               </div>`
                            : ""
                    }

                </div>


                <div class="profile-metrics">


                    <div class="profile-metric">

                        <span>
                            MATERIAL
                        </span>

                        <strong>
                            ${safeNumber(profile.material_g)} g
                        </strong>

                    </div>


                    <div class="profile-metric">

                        <span>
                            TIME
                        </span>

                        <strong>
                            ${safeNumber(profile.time_h)} h
                        </strong>

                    </div>


                    <div class="profile-metric">

                        <span>
                            ENERGY
                        </span>

                        <strong>
                            ${safeNumber(profile.energy_kwh)} kWh
                        </strong>

                    </div>


                    <div class="profile-metric">

                        <span>
                            CO₂e
                        </span>

                        <strong>
                            ${safeNumber(profile.co2_kg)} kg
                        </strong>

                    </div>


                    <div class="profile-metric">

                        <span>
                            WALLS
                        </span>

                        <strong>
                            ${safeNumber(profile.walls)}
                        </strong>

                    </div>


                    <div class="profile-metric">

                        <span>
                            INFILL
                        </span>

                        <strong>
                            ${safeNumber(profile.infill)}%
                        </strong>

                    </div>

                </div>


                <div class="confidence">

                    <div class="confidence-header">

                        <span>
                            STRENGTH CONFIDENCE
                        </span>

                        <strong>
                            ${safeNumber(profile.confidence)}%
                        </strong>

                    </div>


                    <div class="confidence-bar">

                        <div
                            class="confidence-fill"
                            style="width:${Math.min(
                                100,
                                Math.max(
                                    0,
                                    Number(
                                        profile.confidence || 0
                                    )
                                )
                            )}%"
                        ></div>

                    </div>

                </div>


                <button
                    class="select-profile"
                    data-profile="${escapeHTML(profile.id || "")}"
                >

                    ${
                        recommended
                            ? "Use Recommended"
                            : "Select Profile"
                    }

                </button>

            `;


            const button =
                card.querySelector(
                    ".select-profile"
                );


            if (button) {

                button.addEventListener(
                    "click",
                    function () {

                        selectProfile(
                            profile.id
                        );

                    }
                );

            }


            container.appendChild(
                card
            );

        }
    );

}


/* ============================================================
   PROFILE SELECTION
   ============================================================ */

function selectProfile(profileId) {

    SELECTED_PROFILE =
        profileId;


    document
        .querySelectorAll(
            ".profile"
        )
        .forEach(
            function (profile) {

                profile.classList.remove(
                    "selected"
                );

            }
        );


    const buttons =
        document.querySelectorAll(
            ".select-profile"
        );


    buttons.forEach(
        function (button) {

            if (
                button.dataset.profile ===
                profileId
            ) {

                button.closest(
                    ".profile"
                )?.classList.add(
                    "selected"
                );

            }

        }
    );


    if (
        window.orca &&
        typeof window.orca.postMessage ===
        "function"
    ) {

        window.orca.postMessage({

            type: "select_profile",

            profile: profileId

        });

    }


    setStatus(
        "Selected " +
        profileId +
        " optimization profile.",
        "success"
    );


    updateActionCard(
        profileId
    );

}


/* ============================================================
   FINAL OPTIMIZE BUTTON
   ============================================================ */

function optimizeSelected() {

    if (!DATA) {

        setStatus(
            "Analyze a model before optimizing.",
            "warning"
        );

        return;

    }


    const profile =
        SELECTED_PROFILE ||
        "balanced";


    setStatus(
        "Applying " +
        profile +
        " optimization...",
        "loading"
    );


    if (
        window.orca &&
        typeof window.orca.postMessage ===
        "function"
    ) {

        window.orca.postMessage({

            type: "optimize",

            profile: profile,

            intent:
                el("intent")?.value || ""

        });


        /*
           Current Python plugin may not yet have an
           "optimize" handler. That is okay.

           The message is now ready for the next
           Python-side implementation.
        */

    } else {

        setTimeout(
            function () {

                setStatus(
                    "Demo optimization complete.",
                    "success"
                );

            },
            800
        );

    }

}


/* ============================================================
   CHANGES
   ============================================================ */

function renderChanges(changes) {

    const container =
        el("changes");


    if (!container) {
        return;
    }


    container.innerHTML = "";


    if (!changes.length) {

        container.innerHTML = `
            <div class="empty-state">
                No recommendations yet.
            </div>
        `;

        return;

    }


    changes.forEach(
        function (change) {

            const row =
                document.createElement(
                    "div"
                );


            row.className =
                "change";


            const severity =
                change.severity ||
                "medium";


            row.innerHTML = `

                <span
                    class="change-dot ${escapeHTML(severity)}"
                ></span>


                <div class="change-content">

                    <div class="change-title">
                        ${escapeHTML(change.title || "Recommendation")}
                    </div>

                    <div class="change-body">
                        ${escapeHTML(change.body || "")}
                    </div>

                </div>

            `;


            container.appendChild(
                row
            );

        }
    );

}


/* ============================================================
   ACTION CARD
   ============================================================ */

function updateActionCard(profileId) {

    const actionTitle =
        document.querySelector(
            ".action-title"
        );


    const actionDescription =
        document.querySelector(
            ".action-description"
        );


    if (actionTitle) {

        actionTitle.textContent =
            "Ready to optimize with " +
            profileId +
            "?";

    }


    if (actionDescription) {

        actionDescription.textContent =
            "EcoSlice will use the selected strategy for the next optimization step.";

    }

}


/* ============================================================
   3D ROTATION
   ============================================================ */

function rotatePoint(point) {

    let x = Number(point[0]) || 0;
    let y = Number(point[1]) || 0;
    let z = Number(point[2]) || 0;


    /* X rotation */

    const cosX =
        Math.cos(rotationX);

    const sinX =
        Math.sin(rotationX);


    const y1 =
        y * cosX -
        z * sinX;


    const z1 =
        y * sinX +
        z * cosX;


    y = y1;
    z = z1;


    /* Y rotation */

    const cosY =
        Math.cos(rotationY);

    const sinY =
        Math.sin(rotationY);


    const x1 =
        x * cosY +
        z * sinY;


    const z2 =
        -x * sinY +
        z * cosY;


    x = x1;
    z = z2;


    return [
        x,
        y,
        z
    ];

}


/* ============================================================
   DRAW
   ============================================================ */

function draw() {

    if (!canvas || !ctx) {
        return;
    }


    const rect =
        canvas.getBoundingClientRect();


    const width =
        rect.width;


    const height =
        rect.height;


    ctx.clearRect(
        0,
        0,
        width,
        height
    );


    /* Background */

    const gradient =
        ctx.createLinearGradient(
            0,
            0,
            0,
            height
        );


    gradient.addColorStop(
        0,
        "#07191c"
    );


    gradient.addColorStop(
        1,
        "#031012"
    );


    ctx.fillStyle =
        gradient;


    ctx.fillRect(
        0,
        0,
        width,
        height
    );


    drawGrid(
        width,
        height
    );


    if (
        !DATA ||
        !DATA.mesh ||
        !Array.isArray(
            DATA.mesh.vertices
        ) ||
        !DATA.mesh.vertices.length
    ) {

        drawEmptyState();

        return;

    }


    const vertices =
        DATA.mesh.vertices;


    const stresses =
        Array.isArray(
            DATA.mesh.stress
        )
            ? DATA.mesh.stress
            : [];


    const points =
        vertices.map(
            rotatePoint
        );


    let maxDimension = 1;


    points.forEach(
        function (point) {

            maxDimension =
                Math.max(
                    maxDimension,
                    Math.abs(point[0]),
                    Math.abs(point[1]),
                    Math.abs(point[2])
                );

        }
    );


    const scale =
        Math.min(
            width,
            height
        )
        /
        (
            maxDimension *
            2.5
        )
        *
        zoom;


    function project(point) {

        return [

            width / 2 +
            point[0] * scale,

            height / 2 -
            point[1] * scale

        ];

    }


    /*
       Draw model triangles
    */

    for (
        let i = 0;
        i < vertices.length;
        i += 3
    ) {

        if (
            i + 2 >=
            vertices.length
        ) {
            break;
        }


        const p1 =
            project(
                points[i]
            );


        const p2 =
            project(
                points[i + 1]
            );


        const p3 =
            project(
                points[i + 2]
            );


        let color =
            "rgba(45,130,132,.72)";


        if (
            MODE === "stress"
        ) {

            const stress =
                stresses[i] || 0;


            color =
                stressColor(
                    stress
                );

        }


        ctx.beginPath();

        ctx.moveTo(
            p1[0],
            p1[1]
        );

        ctx.lineTo(
            p2[0],
            p2[1]
        );

        ctx.lineTo(
            p3[0],
            p3[1]
        );

        ctx.closePath();


        ctx.fillStyle =
            color;


        ctx.fill();


        ctx.strokeStyle =
            "rgba(130,240,235,.08)";


        ctx.lineWidth = 0.5;

        ctx.stroke();

    }


    /*
       Supports
    */

    if (
        MODE === "supports" &&
        Array.isArray(
            DATA.supports
        )
    ) {

        drawSupports(
            DATA.supports,
            project
        );

    }

}


/* ============================================================
   GRID
   ============================================================ */

function drawGrid(
    width,
    height
) {

    ctx.save();


    ctx.strokeStyle =
        "rgba(50,210,200,.075)";


    ctx.lineWidth = 1;


    const gridSize = 45;


    for (
        let x = 0;
        x < width;
        x += gridSize
    ) {

        ctx.beginPath();

        ctx.moveTo(
            x,
            0
        );

        ctx.lineTo(
            x,
            height
        );

        ctx.stroke();

    }


    for (
        let y = 0;
        y < height;
        y += gridSize
    ) {

        ctx.beginPath();

        ctx.moveTo(
            0,
            y
        );

        ctx.lineTo(
            width,
            y
        );

        ctx.stroke();

    }


    ctx.restore();

}


/* ============================================================
   SUPPORT VISUALIZATION
   ============================================================ */

function drawSupports(
    supports,
    project
) {

    supports.forEach(
        function (support) {

            if (
                !support.top ||
                !support.bottom
            ) {
                return;
            }


            const top =
                project(
                    rotatePoint(
                        support.top
                    )
                );


            const bottom =
                project(
                    rotatePoint(
                        support.bottom
                    )
                );


            /*
               Main support column
            */

            ctx.strokeStyle =
                "#f4d34f";


            ctx.lineWidth = 3;


            ctx.beginPath();

            ctx.moveTo(
                top[0],
                top[1]
            );

            ctx.lineTo(
                bottom[0],
                bottom[1]
            );

            ctx.stroke();


            /*
               Support contact point
            */

            ctx.fillStyle =
                "#f4d34f";


            ctx.beginPath();

            ctx.arc(
                top[0],
                top[1],
                4,
                0,
                Math.PI * 2
            );

            ctx.fill();


            /*
               Support base
            */

            ctx.beginPath();

            ctx.arc(
                bottom[0],
                bottom[1],
                2.5,
                0,
                Math.PI * 2
            );

            ctx.fill();

        }
    );

}


/* ============================================================
   STRESS COLORS
   ============================================================ */

function stressColor(value) {

    value =
        Math.max(
            0,
            Math.min(
                1,
                Number(value) || 0
            )
        );


    if (
        value < 0.5
    ) {

        const t =
            value * 2;


        const r =
            Math.round(
                61 +
                180 * t
            );


        const g =
            Math.round(
                217 -
                80 * t
            );


        const b =
            Math.round(
                181 -
                110 * t
            );


        return `
            rgb(
                ${r},
                ${g},
                ${b}
            )
        `;

    }


    const t =
        (
            value -
            0.5
        ) * 2;


    return `
        rgb(
            241,
            ${Math.round(
                137 -
                60 * t
            )},
            ${Math.round(
                101 -
                70 * t
            )}
        )
    `;

}


/* ============================================================
   EMPTY CANVAS
   ============================================================ */

function drawEmptyState() {

    const rect =
        canvas.getBoundingClientRect();


    const width =
        rect.width;


    const height =
        rect.height;


    ctx.textAlign =
        "center";


    ctx.fillStyle =
        "#5b8581";


    ctx.font =
        "600 16px sans-serif";


    ctx.fillText(
        "Load a model in OrcaSlicer",
        width / 2,
        height / 2 - 10
    );


    ctx.font =
        "13px sans-serif";


    ctx.fillStyle =
        "#416361";


    ctx.fillText(
        "EcoSlice will analyze its geometry automatically.",
        width / 2,
        height / 2 + 18
    );

}


/* ============================================================
   NOTIFICATIONS
   ============================================================ */

function showNotification(message) {

    setStatus(
        message,
        "warning"
    );

}


/* ============================================================
   DEMO DATA
   ============================================================ */

function createDemoData() {

    /*
       This is ONLY a browser fallback.

       When running inside OrcaSlicer,
       real Python analysis data will replace this.
    */

    const vertices = [];


    const size = 40;


    const cube = [

        [-size,-size,-size],
        [ size,-size,-size],
        [ size, size,-size],

        [-size,-size,-size],
        [ size, size,-size],
        [-size, size,-size],

        [-size,-size,size],
        [ size, size,size],
        [ size,-size,size],

        [-size,-size,size],
        [-size, size,size],
        [ size, size,size],

        [-size,-size,-size],
        [-size,-size,size],
        [ size,-size,size],

        [-size,-size,-size],
        [ size,-size,size],
        [ size,-size,-size],

        [-size,size,-size],
        [ size,size,-size],
        [ size,size,size],

        [-size,size,-size],
        [ size,size,size],
        [-size,size,size]

    ];


    cube.forEach(
        function (point) {

            vertices.push(
                point
            );

        }
    );


    const stress =
        vertices.map(
            function (_, i) {

                return (
                    i /
                    vertices.length
                );

            }
        );


    const supports = [

        {
            top: [
                -25,
                -35,
                -20
            ],

            bottom: [
                -25,
                -65,
                -20
            ]

        },

        {
            top: [
                0,
                -35,
                -20
            ],

            bottom: [
                0,
                -65,
                -20
            ]

        },

        {
            top: [
                25,
                -35,
                -20
            ],

            bottom: [
                25,
                -65,
                -20
            ]

        }

    ];


    return {

        objects: [

            {
                name:
                    "Demo Part"
            }

        ],


        geometry: {

            dimensions_mm: [
                80,
                80,
                80
            ],

            volume_mm3:
                512000,

            triangles:
                vertices.length / 3,

            support_risk:
                18.5,

            manifold:
                true

        },


        analysis: {

            overhang_faces:
                42,

            stress_max:
                0.67,

            support_points:
                supports.length

        },


        mesh: {

            vertices:
                vertices,

            stress:
                stress

        },


        supports:
            supports,


        profiles: [

            {
                id: "eco",

                name: "Eco",

                tag: "",

                material_g: 6.1,

                time_h: 0.73,

                energy_kwh: 0.09,

                co2_kg: 0.03,

                walls: 2,

                infill: 12,

                confidence: 71

            },

            {
                id: "balanced",

                name: "Balanced",

                tag: "RECOMMENDED",

                material_g: 9.4,

                time_h: 1.12,

                energy_kwh: 0.13,

                co2_kg: 0.05,

                walls: 4,

                infill: 30,

                confidence: 87

            },

            {
                id: "maximum",

                name: "Maximum Strength",

                tag: "",

                material_g: 13.4,

                time_h: 1.60,

                energy_kwh: 0.19,

                co2_kg: 0.07,

                walls: 6,

                infill: 55,

                confidence: 96

            }

        ],


        changes: [

            {
                severity: "high",

                title:
                    "Increase wall count",

                body:
                    "Increase perimeter walls in high-load regions to improve structural robustness."

            },

            {
                severity: "medium",

                title:
                    "Reduce unnecessary infill",

                body:
                    "Use targeted infill rather than increasing density across the entire part."

            },

            {
                severity: "low",

                title:
                    "Reduce support material",

                body:
                    "Several support regions can potentially be avoided through orientation changes."

            }

        ]

    };

}


/* ============================================================
   SAFETY / FORMATTING HELPERS
   ============================================================ */

function safeNumber(value) {

    if (
        value === undefined ||
        value === null ||
        Number.isNaN(
            Number(value)
        )
    ) {

        return "—";

    }


    return Number(value)
        .toLocaleString(
            undefined,
            {
                maximumFractionDigits: 2
            }
        );

}


function escapeHTML(value) {

    return String(
        value ?? ""
    )
        .replace(
            /&/g,
            "&amp;"
        )
        .replace(
            /</g,
            "&lt;"
        )
        .replace(
            />/g,
            "&gt;"
        )
        .replace(
            /"/g,
            "&quot;"
        )
        .replace(
            /'/g,
            "&#039;"
        );

}


/* ============================================================
   EXPOSE FUNCTIONS TO INLINE HTML
   ============================================================ */

window.setMode =
    setMode;

window.setSection =
    setSection;

window.setIntent =
    setIntent;

window.analyze =
    analyze;

window.selectProfile =
    selectProfile;

window.optimizeSelected =
    optimizeSelected;