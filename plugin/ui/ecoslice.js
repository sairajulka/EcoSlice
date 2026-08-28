let selectedOption = "balanced";


const cards = document.querySelectorAll(
    ".option-card"
);


const buttons = document.querySelectorAll(
    ".select-button"
);


function selectOption(option) {

    selectedOption = option;

    cards.forEach(card => {

        card.classList.remove(
            "selected"
        );

    });

    const selected =
        document.querySelector(
            `[data-option="${option}"]`
        );

    if (selected) {

        selected.classList.add(
            "selected"
        );

    }

}


buttons.forEach(button => {

    button.addEventListener(
        "click",
        event => {

            event.stopPropagation();

            const card =
                button.closest(
                    ".option-card"
                );

            selectOption(
                card.dataset.option
            );

        }
    );

});


cards.forEach(card => {

    card.addEventListener(
        "click",
        () => {

            selectOption(
                card.dataset.option
            );

        }
    );

});


document
    .getElementById("optimize")
    .addEventListener(
        "click",
        () => {

            /*
             * Send the selected optimization
             * back to the Python plugin.
             */

            if (
                window.orca &&
                window.orca.postMessage
            ) {

                window.orca.postMessage({

                    type: "optimize",

                    option: selectedOption

                });

            }

            else {

                console.log(
                    "EcoSlice optimization:",
                    selectedOption
                );

            }

        }
    );


/*
 * Start with Balanced selected.
 */

selectOption("balanced");