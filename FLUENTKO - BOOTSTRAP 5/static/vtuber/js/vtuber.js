window.addEventListener("DOMContentLoaded", async () => {

    const canvas = document.getElementById("live2dCanvas");

    const app = new PIXI.Application({
        view: canvas,
        autoStart: true,
        resizeTo: canvas.parentElement,
        transparent: true,
        backgroundAlpha: 0   // 👈 THIS removes black background
    });

    // Load Live2D model
    const model = await PIXI.live2d.Live2DModel.from(
        "/static/vtuber/model/VT_student/VT_student.model3.json"
    );

    app.stage.addChild(model);

    // center model

    model.x = app.renderer.width / 2;
    model.y = app.renderer.height + 660;
    model.scale.set(0.35);

    model.anchor.set(0.5, 1);
    // simple idle animation
    model.motion("Idle");

});

window.addEventListener("resize", () => {
    model.x = app.renderer.width / 2;
    model.y = app.renderer.height * 0.75;
});
